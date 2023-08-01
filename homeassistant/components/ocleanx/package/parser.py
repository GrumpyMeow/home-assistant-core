from enum import Enum, auto
import logging
import time

from bleak import BleakError, BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
    retry_bluetooth_connection_error,
)
from bluetooth_data_tools import short_address
from bluetooth_sensor_state_data import BluetoothData
from home_assistant_bluetooth import BluetoothServiceInfo
from sensor_state_data import SensorDeviceClass, SensorUpdate, Units
from sensor_state_data.enum import StrEnum

from .const import (
    BRUSHING_UPDATE_INTERVAL_SECONDS,
    CHARACTERISTIC_BATTERY_LEVEL,
    CHARACTERISTIC_COMMAND,
    NOT_BRUSHING_UPDATE_INTERVAL_SECONDS,
    TIMEOUT_RECENTLY_BRUSHING,
)


class OcleanXSensor(StrEnum):
    BATTERY_PERCENT = "battery_percent"


OCLEANX_MANUFACTURER = 10147


class Models(Enum):
    OcleanX = auto()


_LOGGER = logging.getLogger(__name__)


class OcleanXBluetoothDeviceData(BluetoothData):
    def __init__(self) -> None:
        super().__init__()
        # If this is True, we are currently brushing or were brushing as of the last advertisement data
        self._brushing = False
        self._last_brush = 0.0

    def _start_update(self, data: BluetoothServiceInfo) -> None:
        """Update from BLE advertisement data."""
        manufacturer_data = data.manufacturer_data
        address = data.address
        if OCLEANX_MANUFACTURER not in manufacturer_data:
            return None
        data = manufacturer_data[OCLEANX_MANUFACTURER]
        self.set_device_manufacturer("OcleanX")
        # _LOGGER.debug("Parsing OcleanX sensor: %s", data)
        msg_length = len(data)
        if msg_length != 4:
            _LOGGER.debug(
                "Ignoring OcleanX BLE advertisement data since unexpected message length: %d",
                msg_length,
            )
            return

        self.set_device_type("Oclean X")
        # name = f"{model_info.device_type} {short_address(address)}"
        name = f"Oclean X {short_address(address)}"
        self.set_device_name(name)
        self.set_title(name)
        # tb_state = STATES.get(state, f"unknown state {state}")
        # tb_mode = modes.get(mode, f"unknown mode {mode}")
        # tb_pressure = PRESSURE.get(pressure, f"unknown pressure {pressure}")
        # tb_sector = SECTOR_MAP.get(sector, f"unknown sector code {sector}")

        # self.update_sensor(str(OralBSensor.TIME), None, brush_time, None, "Time")
        # if brush_time == 0 and tb_state != "running":
        #     # When starting up, sector is not accurate.
        #     self.update_sensor(
        #         str(OralBSensor.SECTOR), None, "no sector", None, "Sector"
        #     )
        # else:
        #     self.update_sensor(str(OralBSensor.SECTOR), None, tb_sector, None, "Sector")
        # if no_of_sectors is not None:
        #     self.update_sensor(
        #         str(OralBSensor.NUMBER_OF_SECTORS),
        #         None,
        #         no_of_sectors,
        #         None,
        #         "Number of sectors",
        #     )
        # if sector_timer is not None:
        #     self.update_sensor(
        #         str(OralBSensor.SECTOR_TIMER), None, sector_timer, None, "Sector Timer"
        #     )
        # self.update_sensor(
        #     str(OralBSensor.TOOTHBRUSH_STATE), None, tb_state, None, "Toothbrush State"
        # )
        # self.update_sensor(
        #     str(OralBSensor.PRESSURE), None, tb_pressure, None, "Pressure"
        # )
        # self.update_sensor(str(OralBSensor.MODE), None, tb_mode, None, "Mode")
        # self.update_binary_sensor(
        #     str(OralBBinarySensor.BRUSHING), bool(state == 3), None, "Brushing"
        # )
        # if state == 3:
        #     self._brushing = True
        #     self._last_brush = time.monotonic()
        # else:
        #     self._brushing = False

    def poll_needed(
        self, service_info: BluetoothServiceInfo, last_poll: float | None
    ) -> bool:
        """This is called every time we get a service_info for a device. It means the
        device is working and online.
        """
        if last_poll is None:
            return True
        update_interval = NOT_BRUSHING_UPDATE_INTERVAL_SECONDS
        if (
            self._brushing
            or time.monotonic() - self._last_brush <= TIMEOUT_RECENTLY_BRUSHING
        ):
            update_interval = BRUSHING_UPDATE_INTERVAL_SECONDS
        return last_poll > update_interval

    @retry_bluetooth_connection_error()
    async def _get_payload(self, client: BleakClientWithServiceCache) -> None:
        """Get the payload from the brush using its gatt_characteristics."""
        # for service in await client.get_services():
        #     _LOGGER.debug("Service %s", service)

        for service in client.services:
            for characteristic in service.characteristics:
                try:
                    value = await client.read_gatt_char(characteristic)
                    _LOGGER.debug(
                        "%s %s %s",
                        characteristic.service_uuid,
                        characteristic.uuid,
                        value,
                    )
                except:
                    _LOGGER.debug(
                        "%s %s %s",
                        characteristic.service_uuid,
                        characteristic.uuid,
                        "NA",
                    )

        client.write_gatt_char(CHARACTERISTIC_COMMAND, [0x0A, 0x03])  # Received 0x00
        client.write_gatt_char(CHARACTERISTIC_COMMAND, [0x03, 0x0A])  # Received 0x03

        # for service in client.services.services:
        #     _LOGGER.debug("OcleanX _get_payload service: %s", service)
        # for characteristic in client.services.characteristics:
        #     _LOGGER.debug("OcleanX _get_payload characteristic: %s", characteristic)

        battery_char = client.services.get_characteristic(CHARACTERISTIC_BATTERY_LEVEL)
        battery_payload = await client.read_gatt_char(battery_char)
        # pressure_char = client.services.get_characteristic(CHARACTERISTIC_PRESSURE)
        # pressure_payload = await client.read_gatt_char(pressure_char)
        # tb_pressure = ACTIVE_CONNECTION_PRESSURE.get(
        #     pressure_payload[0], f"unknown pressure {pressure_payload[0]}"
        # )
        # self.update_sensor(
        #     str(OralBSensor.PRESSURE), None, tb_pressure, None, "Pressure"
        # )
        self.update_sensor(
            str(OcleanXSensor.BATTERY_PERCENT),
            Units.PERCENTAGE,
            battery_payload[0],
            SensorDeviceClass.BATTERY,
            "Battery",
        )
        _LOGGER.debug("Successfully read active gatt characters")

    async def async_poll(self, ble_device: BLEDevice) -> SensorUpdate:
        """Poll the device to retrieve any values we can't get from passive listening."""
        _LOGGER.debug("Polling OcleanX device: %s", ble_device.address)
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, ble_device.address
        )
        try:
            await self._get_payload(client)
        except BleakError as err:
            _LOGGER.warning(f"Reading gatt characters failed with err: {err}")
        finally:
            await client.disconnect()
            _LOGGER.debug("Disconnected from active bluetooth client")
        return self._finish_update()
