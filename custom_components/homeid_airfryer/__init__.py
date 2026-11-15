"""Philips HomeID Airfryer (SPECTRE HD9285/HD9280/HD9255) integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.const import ATTR_DEVICE_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_DURATION,
    ATTR_FAHRENHEIT,
    ATTR_PRESET,
    ATTR_RECIPE_ID,
    ATTR_REMAINING,
    ATTR_TEMPERATURE,
    DOMAIN,
    KEEP_WARM_MAX_SECONDS,
    MAX_SECONDS,
    MIN_SECONDS,
    PRESET_IDS,
    PRESETS,
    SERVICE_KEEP_WARM,
    SERVICE_START_COOKING,
    SERVICE_UPDATE_SETTINGS,
)
from .coordinator import HomeIDConfigEntry, HomeIDCoordinator
from .homeid import Status

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_DURATION = vol.All(cv.time_period, cv.positive_timedelta,
                    lambda value: int(value.total_seconds()), vol.Range(MIN_SECONDS, MAX_SECONDS))

START_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_ID): cv.string,
    vol.Required(ATTR_TEMPERATURE): vol.All(vol.Coerce(int), vol.Range(40, 400)),
    vol.Required(ATTR_DURATION): _DURATION,
    vol.Optional(ATTR_FAHRENHEIT, default=False): cv.boolean,
    vol.Optional(ATTR_PRESET, default=PRESETS[0]): vol.In(list(PRESET_IDS)),
    vol.Optional(ATTR_RECIPE_ID): cv.string,
})
UPDATE_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_ID): cv.string,
    vol.Optional(ATTR_TEMPERATURE): vol.All(vol.Coerce(int), vol.Range(40, 400)),
    vol.Exclusive(ATTR_DURATION, "time"): _DURATION,
    vol.Exclusive(ATTR_REMAINING, "time"): _DURATION,
})
KEEP_WARM_SCHEMA = vol.Schema({
    vol.Required(ATTR_DEVICE_ID): cv.string,
    vol.Optional(ATTR_DURATION, default={"minutes": 30}): vol.All(
        _DURATION, vol.Range(max=KEEP_WARM_MAX_SECONDS)),
})


def _status_response(status: Status) -> dict[str, Any]:
    return {
        "state": status.state,
        "temperature": status.temperature,
        "fahrenheit": status.fahrenheit,
        "duration": status.duration_seconds,
        "remaining": status.remaining_seconds,
        "drawer_open": status.drawer_open,
        "preset": status.preset,
        "error": status.error,
    }


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> HomeIDCoordinator:
    device = dr.async_get(hass).async_get(call.data[ATTR_DEVICE_ID])
    if device is not None:
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.domain == DOMAIN and hasattr(entry, "runtime_data"):
                return entry.runtime_data
    raise ServiceValidationError(
        translation_domain=DOMAIN, translation_key="device_not_found")


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services that accept full cooking parameters."""

    async def start_cooking(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        data = call.data
        status = await coordinator.async_command(lambda fryer: fryer.start_cooking(
            data[ATTR_TEMPERATURE], data[ATTR_DURATION], fahrenheit=data[ATTR_FAHRENHEIT],
            preset=PRESET_IDS[data[ATTR_PRESET]], recipe_id=data.get(ATTR_RECIPE_ID)))
        return _status_response(status)

    async def update_settings(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        data = call.data
        if not {ATTR_TEMPERATURE, ATTR_DURATION, ATTR_REMAINING} & data.keys():
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="nothing_to_update")
        status = await coordinator.async_command(lambda fryer: fryer.update_settings(
            temperature=data.get(ATTR_TEMPERATURE), seconds=data.get(ATTR_DURATION),
            remaining_seconds=data.get(ATTR_REMAINING)))
        return _status_response(status)

    async def keep_warm(call: ServiceCall) -> ServiceResponse:
        coordinator = _coordinator(hass, call)
        status = await coordinator.async_command(
            lambda fryer: fryer.keep_warm(call.data[ATTR_DURATION]))
        return _status_response(status)

    for name, handler, schema in (
        (SERVICE_START_COOKING, start_cooking, START_SCHEMA),
        (SERVICE_UPDATE_SETTINGS, update_settings, UPDATE_SCHEMA),
        (SERVICE_KEEP_WARM, keep_warm, KEEP_WARM_SCHEMA),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema,
                                     supports_response=SupportsResponse.OPTIONAL)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HomeIDConfigEntry) -> bool:
    """Connect to the airfryer and set up its entities."""
    coordinator = HomeIDCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HomeIDConfigEntry) -> bool:
    """Unload entities and close the connection."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
