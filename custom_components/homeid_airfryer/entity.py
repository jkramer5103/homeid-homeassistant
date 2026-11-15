"""Base entity for the Philips HomeID Airfryer integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import HomeIDCoordinator


class HomeIDEntity(CoordinatorEntity[HomeIDCoordinator]):
    """An entity attached to the airfryer device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HomeIDCoordinator, key: str) -> None:
        super().__init__(coordinator)
        config = coordinator.config
        self._attr_translation_key = key
        self._attr_unique_id = f"{config.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config.device_id)},
            manufacturer=MANUFACTURER,
            model=config.model,
            name="Airfryer",
        )
