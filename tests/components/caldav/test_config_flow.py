"""Test the Caldav config flow."""
from unittest.mock import patch

from caldav.lib.error import DAVError

from homeassistant.components.caldav.const import (
    CONF_CALENDAR,
    CONF_CALENDARS,
    CONF_CUSTOM_CALENDARS,
    CONF_DAYS,
    CONF_SEARCH,
    DOMAIN,
)
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.const import (
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SOURCE,
    CONF_URL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry

USER_INPUT = {
    CONF_USERNAME: "username",
    CONF_PASSWORD: "password",
    CONF_URL: "http://homeassistant.io",
    CONF_VERIFY_SSL: True,
    CONF_DAYS: 2,
}

IMPORT_INPUT = {
    CONF_USERNAME: "username",
    CONF_PASSWORD: "password",
    CONF_URL: "http://homeassistant.io",
    CONF_VERIFY_SSL: True,
    CONF_DAYS: 2,
    CONF_CALENDARS: ["home", "assistant"],
    CONF_CUSTOM_CALENDARS: [
        {CONF_NAME: "name", CONF_CALENDAR: "calendar", CONF_SEARCH: "search"},
        {CONF_NAME: "name_1", CONF_CALENDAR: "calendar_1", CONF_SEARCH: "search_1"},
    ],
}

OPTIONS_INPUT = {CONF_CALENDARS: [], CONF_CUSTOM_CALENDARS: []}


async def test_user_form(hass: HomeAssistant, mock_connect) -> None:
    """Test we get the user initiated form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={CONF_SOURCE: SOURCE_USER}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    with patch(
        "homeassistant.components.caldav.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "homeassistant.io (username)"

    assert result["data"]
    assert result["data"][CONF_URL] == USER_INPUT[CONF_URL]
    assert result["data"][CONF_USERNAME] == USER_INPUT[CONF_USERNAME]
    assert result["data"][CONF_PASSWORD] == USER_INPUT[CONF_PASSWORD]
    assert result["data"][CONF_DAYS] == USER_INPUT[CONF_DAYS]
    assert result["data"][CONF_VERIFY_SSL] is USER_INPUT[CONF_VERIFY_SSL]
    assert len(mock_setup_entry.mock_calls) == 1


async def test_abort_on_connection_error(hass: HomeAssistant) -> None:
    """Test we abort on connection error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    with patch(
        "homeassistant.components.caldav.caldav.DAVClient.principal",
        side_effect=DAVError(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    with patch(
        "homeassistant.components.caldav.caldav.DAVClient.principal",
        side_effect=Exception(),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_abort_if_already_setup(hass: HomeAssistant) -> None:
    """Test we abort if component is already setup."""
    MockConfigEntry(
        domain=DOMAIN, data={CONF_URL: "url", CONF_USERNAME: "username"}
    ).add_to_hass(hass)

    # Should fail, same MOCK_HOST (import)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={CONF_URL: "url", CONF_USERNAME: "username"},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"

    # Should fail, same MOCK_HOST (flow)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_URL: "url", CONF_USERNAME: "username"},
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_import(hass: HomeAssistant, mock_connect) -> None:
    """Test import step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=IMPORT_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]
    assert result["data"][CONF_URL] == USER_INPUT[CONF_URL]
    assert result["data"][CONF_USERNAME] == USER_INPUT[CONF_USERNAME]
    assert result["data"][CONF_PASSWORD] == USER_INPUT[CONF_PASSWORD]
    assert result["data"][CONF_DAYS] == USER_INPUT[CONF_DAYS]
    assert result["data"][CONF_VERIFY_SSL] is USER_INPUT[CONF_VERIFY_SSL]
    assert result["options"] == OPTIONS_INPUT
