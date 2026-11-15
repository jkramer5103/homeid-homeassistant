"""Control buttons: start, pause, resume, stop."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import KEEP_WARM_MAX_SECONDS, PRESET_IDS
from .coordinator import HomeIDConfigEntry, HomeIDCoordinator, PendingSettings
from .entity import HomeIDEntity
from .homeid import Airfryer, Status


def start_action(pending: PendingSettings) -> Callable[[Airfryer], Awaitable[Status]]:
    """Start a cook from the staged settings (always in Celsius)."""
    settings = PendingSettings(pending.temperature, pending.seconds, pending.preset)
    if settings.preset == PRESET_IDS["keep_warm"]:
        return lambda fryer: fryer.keep_warm(min(settings.seconds, KEEP_WARM_MAX_SECONDS))
    return lambda fryer: fryer.start_cooking(
        settings.temperature, settings.seconds, preset=settings.preset)


@dataclass(frozen=True, kw_only=True)
class HomeIDButtonDescription(ButtonEntityDescription):
    """Describes a control button."""

    action: Callable[[HomeIDCoordinator], Callable[[Airfryer], Awaitable[Status]]]


BUTTONS: tuple[HomeIDButtonDescription, ...] = (
    HomeIDButtonDescription(key="start", action=lambda c: start_action(c.pending)),
    HomeIDButtonDescription(key="pause", action=lambda c: lambda fryer: fryer.pause()),
    HomeIDButtonDescription(key="resume", action=lambda c: lambda fryer: fryer.resume()),
    HomeIDButtonDescription(key="stop", action=lambda c: lambda fryer: fryer.stop()),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HomeIDConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up control buttons."""
    coordinator = entry.runtime_data
    async_add_entities(HomeIDButton(coordinator, description) for description in BUTTONS)


class HomeIDButton(HomeIDEntity, ButtonEntity):
    """Sends one command and waits for the appliance to confirm it."""

    entity_description: HomeIDButtonDescription

    def __init__(self, coordinator: HomeIDCoordinator, description: HomeIDButtonDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        await self.coordinator.async_command(self.entity_description.action(self.coordinator))
