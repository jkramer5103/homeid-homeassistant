"""Program selection used by the Start button."""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import PRESET_IDS, PRESETS
from .coordinator import HomeIDConfigEntry, HomeIDCoordinator
from .entity import HomeIDEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeIDConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the program select."""
    async_add_entities([ProgramSelect(entry.runtime_data)])


class ProgramSelect(HomeIDEntity, SelectEntity, RestoreEntity):
    """Built-in program for the next cook. Temperature and time still apply."""

    _attr_options: ClassVar[list[str]] = list(PRESETS.values())

    def __init__(self, coordinator: HomeIDCoordinator) -> None:
        super().__init__(coordinator, "program_select")

    @property
    def available(self) -> bool:
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state in PRESET_IDS:
            self.coordinator.pending.preset = PRESET_IDS[last.state]

    @property
    def current_option(self) -> str:
        return PRESETS[self.coordinator.pending.preset]

    async def async_select_option(self, option: str) -> None:
        self.coordinator.pending.preset = PRESET_IDS[option]
        self.async_write_ha_state()
