"""Diagnostics with credentials redacted."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_EMAIL
from .coordinator import HomeIDConfigEntry

TO_REDACT = {
    CONF_EMAIL, "client_id", "client_secret", "encryption_key", "refresh_token",
    "device_id", "appliance_id", "thing_name", "macAddress", "mac_address",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HomeIDConfigEntry
) -> dict[str, Any]:
    """Return entry configuration and the latest observed status."""
    coordinator = entry.runtime_data
    status = coordinator.data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT | {"device"})
        | {"device": async_redact_data(entry.data["device"], TO_REDACT)},
        "last_update_success": coordinator.last_update_success,
        "status": None if status is None else async_redact_data(asdict(status), TO_REDACT),
    }
