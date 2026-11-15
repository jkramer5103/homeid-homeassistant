"""Binary sensors for the airfryer."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import ACTIVE_STATES
from .coordinator import HomeIDConfigEntry, HomeIDCoordinator
from .entity import HomeIDEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeIDConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities([DrawerSensor(coordinator), CookingSensor(coordinator), ProblemSensor(coordinator)])


class DrawerSensor(HomeIDEntity, BinarySensorEntity):
    """On when the basket drawer is open."""

    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, coordinator: HomeIDCoordinator) -> None:
        super().__init__(coordinator, "drawer")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.drawer_open


class CookingSensor(HomeIDEntity, BinarySensorEntity):
    """On while a cook is running or paused."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: HomeIDCoordinator) -> None:
        super().__init__(coordinator, "cooking")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.state in ACTIVE_STATES


class ProblemSensor(HomeIDEntity, BinarySensorEntity):
    """On when the appliance reports a nonzero error code."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: HomeIDCoordinator) -> None:
        super().__init__(coordinator, "problem")

    @property
    def is_on(self) -> bool | None:
        error = self.coordinator.data.error
        return None if error is None else error != 0
