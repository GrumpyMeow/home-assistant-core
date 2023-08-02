"""Support for RESTful numbers."""
from __future__ import annotations

import asyncio
from http import HTTPStatus
import logging
from typing import Any

import async_timeout
import httpx
import voluptuous as vol

from homeassistant.components.number import DEVICE_CLASSES_SCHEMA, NumberEntity
from homeassistant.const import (
    CONF_AUTHENTICATION,
    CONF_DEVICE_CLASS,
    CONF_HEADERS,
    CONF_MAXIMUM,
    CONF_METHOD,
    CONF_MINIMUM,
    CONF_PARAMS,
    CONF_PASSWORD,
    CONF_RESOURCE,
    CONF_TIMEOUT,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
    CONF_VALUE_TEMPLATE,
    CONF_VERIFY_SSL,
    HTTP_BASIC_AUTHENTICATION,
    HTTP_DIGEST_AUTHENTICATION,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import PlatformNotReady
from homeassistant.helpers import config_validation as cv, template
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.template_entity import (
    TEMPLATE_ENTITY_BASE_SCHEMA,
    TemplateEntity,
)
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

_LOGGER = logging.getLogger(__name__)
CONF_BODY_GET = "body_get"
CONF_BODY_SET = "body_set"
CONF_STATE_RESOURCE = "state_resource"

DEFAULT_METHOD = "post"
DEFAULT_NAME = "REST Number"
DEFAULT_TIMEOUT = 10
DEFAULT_VERIFY_SSL = True

SUPPORT_REST_METHODS = ["post", "put", "patch"]

PLATFORM_SCHEMA = cv.PLATFORM_SCHEMA_BASE.extend(
    {
        **TEMPLATE_ENTITY_BASE_SCHEMA.schema,
        vol.Required(CONF_RESOURCE): cv.url,
        vol.Optional(CONF_STATE_RESOURCE): cv.url,
        vol.Optional(CONF_HEADERS): {cv.string: cv.template},
        vol.Optional(CONF_PARAMS): {cv.string: cv.template},
        vol.Optional(CONF_BODY_GET, default=None): cv.template,
        vol.Optional(CONF_BODY_SET, default=None): cv.template,
        vol.Optional(CONF_VALUE_TEMPLATE): cv.template,
        vol.Optional(CONF_METHOD, default=DEFAULT_METHOD): vol.All(
            vol.Lower, vol.In(SUPPORT_REST_METHODS)
        ),
        vol.Optional(CONF_DEVICE_CLASS): DEVICE_CLASSES_SCHEMA,
        vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
        vol.Optional(CONF_AUTHENTICATION): vol.In(
            [HTTP_BASIC_AUTHENTICATION, HTTP_DIGEST_AUTHENTICATION]
        ),
        vol.Inclusive(CONF_USERNAME, "authentication"): cv.string,
        vol.Inclusive(CONF_PASSWORD, "authentication"): cv.string,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): cv.boolean,
        vol.Optional(CONF_MAXIMUM, default=None): vol.Any(None, vol.Coerce(int)),
        vol.Optional(CONF_MINIMUM, default=None): vol.Any(None, vol.Coerce(int)),
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the RESTful Number."""
    resource: str = config[CONF_RESOURCE]
    unique_id: str | None = config.get(CONF_UNIQUE_ID)

    try:
        number = RestNumber(hass, config, unique_id)

        req = await number.get_device_state(hass)
        if req.status_code >= HTTPStatus.BAD_REQUEST:
            _LOGGER.error("Got non-ok response from resource: %s", req.status_code)
        else:
            async_add_entities([number])
    except (TypeError, ValueError):
        _LOGGER.error(
            "Missing resource or schema in configuration. "
            "Add http:// or https:// to your URL"
        )
    except (asyncio.TimeoutError, httpx.RequestError) as exc:
        raise PlatformNotReady(f"No route to resource/endpoint: {resource}") from exc


class RestNumber(TemplateEntity, NumberEntity):
    """Representation of a Number that can be changed using REST."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: ConfigType,
        unique_id: str | None,
    ) -> None:
        """Initialize the REST number."""
        TemplateEntity.__init__(
            self, hass, config=config, fallback_name=DEFAULT_NAME, unique_id=unique_id
        )

        auth: httpx.DigestAuth | tuple[str, str] | None = None
        username: str | None = None
        password: str | None = None
        if (username := config.get(CONF_USERNAME)) and (
            password := config.get(CONF_PASSWORD)
        ):
            if config.get(CONF_AUTHENTICATION) == HTTP_DIGEST_AUTHENTICATION:
                auth = httpx.DigestAuth(username, password)
            else:
                auth = httpx.BasicAuth(username, password=password)

        self._resource: str = config[CONF_RESOURCE]
        self._state_resource: str = config.get(CONF_STATE_RESOURCE) or self._resource
        self._method: str = config[CONF_METHOD]
        self._headers: dict[str, template.Template] | None = config.get(CONF_HEADERS)
        self._params: dict[str, template.Template] | None = config.get(CONF_PARAMS)
        self._auth = auth
        self._body_get: template.Template = config[CONF_BODY_GET]
        self._body_set: template.Template = config[CONF_BODY_SET]
        self._timeout: int = config[CONF_TIMEOUT]
        self._verify_ssl: bool = config[CONF_VERIFY_SSL]

        self._attr_native_min_value = config[CONF_MINIMUM]
        self._attr_native_max_value = config[CONF_MAXIMUM]
        self._attr_device_class = config.get(CONF_DEVICE_CLASS)

        self._body_get.hass = hass
        self._body_set.hass = hass

        self._value_template: template.Template | None = config.get(CONF_VALUE_TEMPLATE)
        if (value_template := self._value_template) is not None:
            value_template.hass = hass

        template.attach(hass, self._headers)
        template.attach(hass, self._params)

    async def set_device_state(self, body: Any) -> httpx.Response:
        """Send a state update to the device."""
        websession = get_async_client(self.hass, self._verify_ssl)

        rendered_headers = template.render_complex(self._headers, parse_result=False)
        rendered_params = template.render_complex(self._params)

        async with async_timeout.timeout(self._timeout):
            req: httpx.Response = await getattr(websession, self._method)(
                self._resource,
                auth=self._auth,
                data=bytes(body, "utf-8"),
                headers=rendered_headers,
                params=rendered_params,
            )
            return req

    async def async_update(self) -> None:
        """Get the current state, catching errors."""

        try:
            await self.get_device_state(self.hass)
        except asyncio.TimeoutError:
            _LOGGER.exception("Timed out while fetching data")
        except httpx.RequestError as err:
            _LOGGER.exception("Error while fetching data: %s", err)

    async def get_device_state(self, hass: HomeAssistant) -> httpx.Response:
        """Get the latest data from REST API and update the state."""
        body = self._body_get.async_render(parse_result=False)

        websession = get_async_client(hass, self._verify_ssl)

        rendered_headers = template.render_complex(self._headers, parse_result=False)
        rendered_params = template.render_complex(self._params)

        async with async_timeout.timeout(self._timeout):
            req: httpx.Response = await getattr(websession, self._method)(
                self._state_resource,
                auth=self._auth,
                data=bytes(body, "utf-8"),
                headers=rendered_headers,
                params=rendered_params,
            )
            text = req.text

        if self._value_template is not None:
            value = self._value_template.async_render_with_possible_json_value(
                text, "None"
            )
            self._attr_native_value = value

        return req

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""

        body_set_t = self._body_set.async_render(
            variables={"value": value}, parse_result=False
        )

        try:
            await self.set_device_state(body_set_t)
        except asyncio.TimeoutError:
            _LOGGER.exception("Timed out while sending data")
        except httpx.RequestError as err:
            _LOGGER.exception("Error while sending data: %s", err)

        self._attr_native_value = value
        self.async_write_ha_state()

