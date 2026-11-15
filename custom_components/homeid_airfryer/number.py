"""Cooking setpoints: staged for the next start, or applied live while cooking."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberMode, RestoreNumber
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ACTIVE_STATES, MAX_SECONDS, MAX_TEMP_C, MIN_SECONDS, MIN_TEMP_C
from .coordinator import HomeIDConfigEntry, HomeIDCoordinator
from .entity import HomeIDEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeIDConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up setpoint numbers."""
    coordinator = entry.runtime_data
    async_add_entities([TemperatureNumber(coordinator), CookTimeNumber(coordinator)])


def celsius_to_device(coordinator: HomeIDCoordinator, celsius: int) -> int:
    """Convert a Celsius setpoint into the appliance's reported unit."""
    if coordinator.data and coordinator.data.fahrenheit:
        return round(celsius * 9 / 5 + 32)
    return celsius


class _SetpointNumber(HomeIDEntity, RestoreNumber):
    _attr_mode = NumberMode.BOX

    @property
    def _active(self) -> bool:
        return self.coordinator.data is not None and self.coordinator.data.state in ACTIVE_STATES

    @property
    def available(self) -> bool:
        # Staging a value for the next cook does not need a live connection.
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_number_data()) and last.native_value is not None:
            self._restore(int(last.native_value))


class TemperatureNumber(_SetpointNumber):
    """Cooking temperature in degrees Celsius."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = MIN_TEMP_C
    _attr_native_max_value = MAX_TEMP_C
    _attr_native_step = 5

    def __init__(self, coordinator: HomeIDCoordinator) -> None:
        super().__init__(coordinator, "temperature")

    def _restore(self, value: int) -> None:
        if MIN_TEMP_C <= value <= MAX_TEMP_C:
            self.coordinator.pending.temperature = value

    @property
    def native_value(self) -> int:
        return self.coordinator.pending.temperature

    async def async_set_native_value(self, value: float) -> None:
        temperature = round(value)
        if self._active:
            await self.coordinator.async_command(
                lambda fryer: fryer.update_settings(
                    temperature=celsius_to_device(self.coordinator, temperature)))
        self.coordinator.pending.temperature = temperature
        self.async_write_ha_state()


class CookTimeNumber(_SetpointNumber):
    """Cook duration in minutes; while cooking it sets the remaining time."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = MIN_SECONDS // 60
    _attr_native_max_value = MAX_SECONDS // 60
    _attr_native_step = 1

    def __init__(self, coordinator: HomeIDCoordinator) -> None:
        super().__init__(coordinator, "cook_time")

    def _restore(self, value: int) -> None:
        if MIN_SECONDS <= value * 60 <= MAX_SECONDS:
            self.coordinator.pending.seconds = value * 60

    @property
    def native_value(self) -> int:
        return self.coordinator.pending.seconds // 60

    async def async_set_native_value(self, value: float) -> None:
        seconds = round(value) * 60
        if not MIN_SECONDS <= seconds <= MAX_SECONDS:
            raise HomeAssistantError("Cook time must be 1 to 60 minutes")
        if self._active:
            await self.coordinator.async_command(
                lambda fryer: fryer.update_settings(remaining_seconds=seconds))
        self.coordinator.pending.seconds = seconds
        self.async_write_ha_state()
