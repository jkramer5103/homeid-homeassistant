"""Connection management and polling for one HomeID airfryer."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEVICE,
    DEFAULT_SECONDS,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    SCAN_INTERVAL_CLOUD,
    SCAN_INTERVAL_LOCAL,
    TRANSPORT_CLOUD,
)
from .homeid import Airfryer, CommandError, DeviceConfig, Status
from .homeid._vendor.cloud_auth import CloudAuthError, CloudConnectionError

_LOGGER = logging.getLogger(__name__)

type HomeIDConfigEntry = ConfigEntry[HomeIDCoordinator]


@dataclass
class PendingSettings:
    """Settings used by the Start button; edited through number/select entities."""

    temperature: int = DEFAULT_TEMPERATURE
    seconds: int = DEFAULT_SECONDS
    preset: int = 0


def device_config(entry: ConfigEntry) -> DeviceConfig:
    """Build a client configuration from stored entry data."""
    return DeviceConfig(**entry.data[CONF_DEVICE])


class HomeIDCoordinator(DataUpdateCoordinator[Status]):
    """Owns the client connection; reconnects after failures."""

    config_entry: HomeIDConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HomeIDConfigEntry) -> None:
        self.config = device_config(entry)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {self.config.device_id}",
            update_interval=SCAN_INTERVAL_CLOUD
            if self.config.transport == TRANSPORT_CLOUD
            else SCAN_INTERVAL_LOCAL,
        )
        self.pending = PendingSettings()
        self._client: Airfryer | None = None
        self._connect_lock = asyncio.Lock()

    @property
    def is_cloud(self) -> bool:
        """Return True when the appliance is controlled through FUSION MQTT."""
        return self.config.transport == TRANSPORT_CLOUD

    def _persist(self, updated: DeviceConfig) -> None:
        """Save rotated refresh tokens and exchanged AES keys to the entry."""
        stored = asdict(updated)
        if stored == self.config_entry.data.get(CONF_DEVICE):
            return
        self.hass.config_entries.async_update_entry(
            self.config_entry, data={**self.config_entry.data, CONF_DEVICE: stored}
        )

    async def _ensure_client(self) -> Airfryer:
        async with self._connect_lock:
            if self._client is not None:
                return self._client
            client = Airfryer(self.config, self._persist)
            # __aenter__ connects (MQTT or AES key exchange) and reads status.
            await client.__aenter__()
            self._client = client
            return client

    async def _drop_client(self) -> None:
        async with self._connect_lock:
            client, self._client = self._client, None
        if client is not None:
            try:
                await client.close()
            except Exception:  # closing must never raise
                _LOGGER.debug("Error while closing HomeID client", exc_info=True)

    async def async_shutdown(self) -> None:
        """Close connections when the entry unloads."""
        await super().async_shutdown()
        await self._drop_client()

    async def _async_update_data(self) -> Status:
        try:
            client = await self._ensure_client()
            # Polling must not wake a sleeping appliance; a sleeping one is
            # reported from the cloud shadow (state and error only).
            return await client.status(wake=False)
        except CloudConnectionError as err:
            await self._drop_client()
            raise UpdateFailed(f"HomeID cloud unreachable: {err}") from err
        except CloudAuthError as err:
            await self._drop_client()
            raise ConfigEntryAuthFailed(str(err)) from err
        except (CommandError, aiohttp.ClientError, OSError, TimeoutError) as err:
            # A missed reply on a live MQTT session is not a broken connection;
            # reconnecting would only add another busy port discovery.
            if not isinstance(err, CommandError) or not self._client or not self._client.connected:
                await self._drop_client()
            message = "network request failed" if isinstance(err, aiohttp.ClientError) else str(err)
            raise UpdateFailed(f"Airfryer unavailable: {message}") from err

    async def async_command(self, action: Callable[[Airfryer], Awaitable[Status]]) -> Status:
        """Run a control command and publish the confirmed resulting state."""
        try:
            client = await self._ensure_client()
            status = await action(client)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        except CloudAuthError as err:
            await self._drop_client()
            if not isinstance(err, CloudConnectionError):
                self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(f"HomeID cloud error: {err}") from err
        except (CommandError, aiohttp.ClientError, OSError, TimeoutError) as err:
            # The command may have reached the appliance; refresh to show truth.
            await self.async_request_refresh()
            message = "network request failed" if isinstance(err, aiohttp.ClientError) else str(err)
            raise HomeAssistantError(f"Airfryer command failed: {message}") from err
        self.async_set_updated_data(status)
        return status

    async def async_device_info(self) -> dict[str, Any]:
        """Return appliance metadata for diagnostics."""
        client = await self._ensure_client()
        return await client.device_info()
