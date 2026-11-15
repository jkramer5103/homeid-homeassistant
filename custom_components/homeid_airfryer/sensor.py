"""Sensors reporting the airfryer's observed state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import PRESETS, STATES
from .coordinator import HomeIDConfigEntry
from .entity import HomeIDEntity
from .homeid import Status


@dataclass(frozen=True, kw_only=True)
class HomeIDSensorDescription(SensorEntityDescription):
    """Describes a sensor derived from a Status observation."""

    value: Callable[[Status], str | int | None]


def _state(status: Status) -> str:
    return status.state if status.state in STATES else "unknown"


SENSORS: tuple[HomeIDSensorDescription, ...] = (
    HomeIDSensorDescription(
        key="state",
        device_class=SensorDeviceClass.ENUM,
        options=STATES,
        value=_state,
    ),
    HomeIDSensorDescription(
        key="remaining_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        value=lambda status: status.remaining_seconds,
    ),
    HomeIDSensorDescription(
        key="cook_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        suggested_unit_of_measurement=UnitOfTime.MINUTES,
        value=lambda status: status.duration_seconds,
    ),
    HomeIDSensorDescription(
        key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=0,
        value=lambda status: status.temperature,
    ),
    HomeIDSensorDescription(
        key="program",
        device_class=SensorDeviceClass.ENUM,
        options=[*PRESETS.values(), "custom"],
        value=lambda status: None if status.preset is None else PRESETS.get(status.preset, "custom"),
    ),
    HomeIDSensorDescription(
        key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda status: status.error,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeIDConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensors."""
    coordinator = entry.runtime_data
    async_add_entities(HomeIDSensor(coordinator, description) for description in SENSORS)


class HomeIDSensor(HomeIDEntity, SensorEntity):
    """A value read from the latest airfryer status."""

    entity_description: HomeIDSensorDescription

    def __init__(self, coordinator, description: HomeIDSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Follow the unit the appliance reports for temperatures."""
        if self.entity_description.key == "target_temperature" and self.coordinator.data.fahrenheit:
            return UnitOfTemperature.FAHRENHEIT
        return self.entity_description.native_unit_of_measurement

    @property
    def native_value(self) -> str | int | None:
        """Return the observed value."""
        return self.entity_description.value(self.coordinator.data)
