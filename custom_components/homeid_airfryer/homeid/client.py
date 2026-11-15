"""Public SPECTRE API. Settings and start are separate, acknowledged operations."""

from __future__ import annotations

import asyncio
import base64
import math
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Self

from ._vendor.cloud_api import PhilipsCloudAPI
from ._vendor.local_api import PhilipsLocalAPI
from ._vendor.local_models import LocalDeviceInfo, LocalDeviceState
from ._vendor.mqtt_api import FusionDeviceInfo, PhilipsMQTTClient

# A status-port read normally answers within about a second.
PORT_READ_TIMEOUT = 8.0
# After a wake request the appliance rediscovers its ports before answering.
WAKE_TIMEOUT = 20.0


class CommandError(RuntimeError):
    """A read/write failed or its resulting state could not be confirmed."""


@dataclass
class DeviceConfig:
    """Credentials belong to the user's paired appliance, not an app API key."""

    host: str = ""
    model: str = "HD9285"
    device_id: str = ""
    appliance_id: str = ""
    transport: str = "local"
    use_https: bool = True
    client_id: str = field(default="", repr=False)
    client_secret: str = field(default="", repr=False)
    encryption_key: str = field(default="", repr=False)
    refresh_token: str = field(default="", repr=False)
    thing_name: str = ""
    mqtt_host: str = "ats.prod.eu-da.iot.versuni.com"
    platform_rest_url: str = "prod.eu-da.iot.versuni.com"
    tenant: str = "da"

    def validate(self) -> None:
        if self.model.upper().split("/")[0] not in {"HD9285", "HD9280", "HD9255", "SPECTRE"}:
            raise ValueError("This client supports SPECTRE (HD9285/HD9280/HD9255) only")
        if self.transport == "local":
            if not self.host or any(c in self.host for c in "/?#@"):
                raise ValueError("host must be an appliance IP address or hostname, optionally with port")
            for name in ("client_id", "client_secret"):
                try:
                    decoded = base64.b64decode(getattr(self, name), validate=True)
                except ValueError:
                    raise ValueError(f"{name} must be valid base64") from None
                if not decoded or (name == "client_id" and len(decoded) != 16):
                    raise ValueError(f"{name} has an invalid length")
        elif self.transport == "fusion":
            if not self.refresh_token or not self.thing_name:
                raise ValueError("FUSION requires refresh_token and thing_name")
        else:
            raise ValueError("transport must be local or fusion")


@dataclass(frozen=True)
class Status:
    """A device observation; remaining time is reported, never extrapolated."""

    state: str
    temperature: int | None
    fahrenheit: bool | None
    duration_seconds: int | None
    remaining_seconds: int | None
    drawer_open: bool | None
    preset: int | None
    error: int | None
    observed_at: float
    raw: dict[str, Any] = field(repr=False)
    # "appliance": read from the cooking status port. "shadow": the FUSION
    # cloud's device report, used when the appliance controller is asleep;
    # it carries only state and error.
    source: str = "appliance"

    @classmethod
    def from_properties(cls, properties: dict[str, Any], observed_at: float | None = None) -> Status:
        def integer(name: str) -> int | None:
            value = properties.get(name)
            return value if type(value) is int else None

        def boolean(name: str) -> bool | None:
            value = properties.get(name)
            return value if type(value) is bool else None

        return cls(
            state=properties.get("status", "unknown"), temperature=integer("temp"),
            fahrenheit=boolean("temp_unit"), duration_seconds=integer("time"),
            remaining_seconds=integer("cur_time"), drawer_open=boolean("drawer_open"),
            preset=integer("preset"), error=integer("error"),
            observed_at=time.time() if observed_at is None else observed_at,
            raw=dict(properties),
        )


def cooking_settings(temperature: int, seconds: int, fahrenheit: bool = False,
                     preset: int = 0) -> dict[str, Any]:
    """Use the HD9285 manual ranges, with time encoded in seconds."""
    if type(fahrenheit) is not bool:
        raise ValueError("fahrenheit must be boolean")
    lower, upper = (104, 400) if fahrenheit else (40, 200)
    if type(temperature) is not int or not lower <= temperature <= upper:
        raise ValueError(f"temperature must be an integer in {lower}..{upper}")
    if type(seconds) is not int or not 60 <= seconds <= 3600:
        raise ValueError("duration must be 60..3600 seconds")
    if type(preset) is not int or not 0 <= preset <= 8:
        raise ValueError("preset must be 0..8")
    if preset == 8 and (temperature != (175 if fahrenheit else 80) or seconds > 1800):
        raise ValueError("Keep warm uses fixed 80 C / 175 F for at most 1800 seconds")
    return {"temp": temperature, "time": seconds, "temp_unit": fahrenheit, "preset": preset}


class Airfryer:
    """Async context manager for local HTTPS/AES or FUSION MQTT control."""

    def __init__(self, config: DeviceConfig,
                 save_config: Callable[[DeviceConfig], None] | None = None) -> None:
        config.validate()
        self.config = config
        self._save_config = save_config
        self._api = PhilipsLocalAPI()
        self._cloud = PhilipsCloudAPI()
        self._device = LocalDeviceInfo(
            ip_address=config.host, cpp_id=config.device_id, model_number=config.model,
            client_id=config.client_id, client_secret=config.client_secret,
            use_https=config.use_https, encryption_key=config.encryption_key or None,
            airfryer_port="airfryer", purifier_port=False, espresso_port=False,
        )
        self._mqtt: PhilipsMQTTClient | None = None
        self._latest: Status | None = None
        self._revision = 0
        self._read_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._token_lock = asyncio.Lock()
        self._closed = False

    async def __aenter__(self) -> Self:
        try:
            if self.config.transport == "local":
                if not self.config.use_https and not self._device.encryption_key:
                    key = await self._api.exchange_encryption_key(self._device)
                    if not key:
                        raise CommandError("HTTP device AES key exchange failed")
                    self.config.encryption_key = key
                    if self._save_config:
                        self._save_config(self.config)
                await self.status(wake=False)
            else:
                revision = self._revision
                await self._connect_mqtt()
                # The connect already asks for every port; a second read sent
                # now only collides with it and gets a busy reply. Wait for
                # that answer, then fall back to an explicit read (which does
                # not wake a sleeping appliance just because a client connected).
                if await self._await_port_status(revision, PORT_READ_TIMEOUT) is None:
                    await self.status(wake=False)
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        self._closed = True
        if self._mqtt:
            await asyncio.to_thread(self._mqtt.disconnect)
        await self._api.close()
        await self._cloud.close()

    async def _mqtt_credentials(self) -> tuple[dict[str, Any], str]:
        async with self._token_lock:
            tokens = await self._cloud.refresh_tokens(self.config.refresh_token)
            self.config.refresh_token = tokens.get("refresh_token", self.config.refresh_token)
            if self._save_config:
                self._save_config(self.config)
            signature = await self._cloud.get_mqtt_signature(
                tokens["access_token"], self.config.platform_rest_url, self.config.tenant)
            if not signature.get("signature"):
                raise CommandError("Cloud returned no MQTT signature")
            return tokens, signature["signature"]

    async def _connect_mqtt(self) -> None:
        loop = asyncio.get_running_loop()
        tokens, signature = await self._mqtt_credentials()
        user_id = await self._cloud.get_mqtt_user_id(
            tokens["access_token"], tokens.get("id_token", ""),
            self.config.platform_rest_url, self.config.tenant)
        if not user_id:
            raise CommandError("Cloud returned no MQTT user ID")

        def refresh() -> tuple[str, str]:
            if self._closed:
                raise CommandError("Client is closed")
            future = asyncio.run_coroutine_threadsafe(self._mqtt_credentials(), loop)
            try:
                new_tokens, new_signature = future.result(timeout=30)
            except BaseException:
                future.cancel()
                raise
            return new_tokens["access_token"], new_signature

        self._mqtt = PhilipsMQTTClient(FusionDeviceInfo(
            thing_name=self.config.thing_name, device_id=self.config.device_id,
            tenant=self.config.tenant, mqtt_host=self.config.mqtt_host,
            platform_rest_url=self.config.platform_rest_url, model_number=self.config.model,
            model_name="Spectre", user_id=user_id,
        ), loop=loop, credential_refresh=refresh)
        self._mqtt.set_state_callback(self._on_state)
        await asyncio.to_thread(self._mqtt.connect, tokens["access_token"], signature)

    def _on_state(self, state: LocalDeviceState) -> None:
        properties = state.properties.get("airfryer")
        revision = state.properties.get("_homeid_airfryer_revision", 0)
        if revision > self._revision and isinstance(properties, dict) and properties.get("status"):
            self._latest = Status.from_properties(
                properties, state.properties["_homeid_airfryer_observed_at"])
            self._revision = revision

    @property
    def connected(self) -> bool:
        """Whether the transport is usable; a local client has no session."""
        return not self._closed and (self._mqtt is None or self._mqtt.connected)

    async def status(self, *, wake: bool = True) -> Status:
        """Read a fresh status.

        FUSION firmware (e.g. HD9285 0.5.6) parks the appliance controller in
        standby while Wi-Fi stays online; a parked controller answers no port
        read. With wake=True (used before and after commands) the appliance
        is woken and a real port status is required. With wake=False (for
        passive monitoring) a fresh cloud shadow report is returned instead,
        with source="shadow" and only state/error populated.
        """
        async with self._read_lock:
            return await self._read_status(wake)

    async def _read_status(self, wake: bool = True) -> Status:
        if self._closed:
            raise CommandError("Client is closed")
        if not self._mqtt:
            properties = await self._api.get_airfryer_status(self._device)
            if not isinstance(properties, dict) or not properties.get("status"):
                raise CommandError("No usable airfryer status; check connectivity and credentials")
            self._latest = Status.from_properties(properties)
            return self._latest
        self._check_mqtt()
        status = await self._fresh_port_status(PORT_READ_TIMEOUT)
        if status is not None:
            return status
        if wake:
            # The wake request rediscovers ports, which re-reads Status.
            revision = self._revision
            # Drop the unanswered read so it cannot hold back the re-read.
            self._mqtt._cancel_port_queue()
            await asyncio.to_thread(self._mqtt.wake_airfryer)
            status = await self._await_port_status(revision, WAKE_TIMEOUT)
            if status is not None:
                return status
            raise CommandError("Airfryer did not respond, even after a wake request; check that it is powered")
        return await self._shadow_status()

    def _check_mqtt(self) -> None:
        if self._mqtt is None or not self._mqtt.connected:
            raise CommandError("MQTT is disconnected; cached status is unavailable")
        self._check_appliance_online()

    async def _fresh_port_status(self, timeout: float) -> Status | None:
        assert self._mqtt is not None
        revision = self._revision
        await asyncio.to_thread(self._mqtt.refresh_airfryer_status)
        return await self._await_port_status(revision, timeout)

    async def _await_port_status(self, revision: int, timeout: float) -> Status | None:
        """Wait for a status-port observation newer than `revision`."""
        deadline = asyncio.get_running_loop().time() + timeout
        while self._revision == revision:
            self._check_mqtt()
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.1)
        assert self._latest is not None
        return self._latest

    async def _shadow_status(self) -> Status:
        """Request the device shadow and report its productState."""
        assert self._mqtt is not None

        def shadow() -> dict[str, Any]:
            state = self._mqtt.device_state if self._mqtt else None
            return state.properties if state else {}

        revision = shadow().get("_homeid_shadow_revision", 0)
        await asyncio.to_thread(self._mqtt.request_state)
        deadline = asyncio.get_running_loop().time() + PORT_READ_TIMEOUT
        while shadow().get("_homeid_shadow_revision", 0) == revision:
            self._check_mqtt()
            if asyncio.get_running_loop().time() >= deadline:
                raise CommandError("No fresh status from the appliance or the cloud shadow")
            await asyncio.sleep(0.1)
        properties = shadow()
        state = properties.get("productState")
        if not isinstance(state, str) or not state:
            raise CommandError("Appliance controller is asleep and the cloud reports no state")
        error = properties.get("productError")
        error = int(error) if isinstance(error, (int, str)) and str(error).isdigit() else None
        return Status(
            state=state, temperature=None, fahrenheit=None, duration_seconds=None,
            remaining_seconds=None, drawer_open=None, preset=None, error=error,
            observed_at=properties.get("_homeid_shadow_observed_at", time.time()),
            raw={"productState": state, "productError": properties.get("productError")},
            source="shadow",
        )

    def _check_appliance_online(self) -> None:
        if self._mqtt:
            state = self._mqtt.device_state
            if state and state.properties.get("connected") is False:
                raise CommandError("Airfryer is offline (cloud reports connected=false); plug it in and reconnect")

    async def _write(self, properties: dict[str, Any], *, recipe: bool = False) -> None:
        if self._closed:
            raise CommandError("Client is closed")
        if self._mqtt:
            self._check_appliance_online()
            if not self._mqtt.has_cooking_control_port():
                await asyncio.to_thread(self._mqtt.wake_airfryer)
                deadline = asyncio.get_running_loop().time() + 10
                while not self._mqtt.has_cooking_control_port():
                    if asyncio.get_running_loop().time() >= deadline:
                        raise CommandError("Device did not advertise a cooking control port")
                    await asyncio.sleep(0.2)
            accepted, code, name = await asyncio.to_thread(
                self._mqtt.send_port_command_and_wait,
                "recipe_control" if recipe else "control", "setPort", properties)
            if not accepted:
                raise CommandError(f"Device command unconfirmed or rejected: {name} ({code}); query status before retrying")
        else:
            result = await self._api._request(self._device, "airfryer", method="PUT", data=properties)
            if result is None:
                raise CommandError("Device command unconfirmed or rejected; query status before retrying")

    async def _wait_state(self, expected: set[str], timeout: float = 15) -> Status:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            status = await self.status()
            if status.error:
                raise CommandError(f"Appliance reports error {status.error}")
            if status.state in expected:
                return status
            if asyncio.get_running_loop().time() >= deadline:
                raise CommandError(f"Command acknowledged but state is {status.state}; expected {sorted(expected)}")
            await asyncio.sleep(0.5)

    async def configure(self, temperature: int, seconds: int, *,
                        fahrenheit: bool = False, preset: int = 0,
                        recipe_id: str | None = None) -> Status:
        settings = cooking_settings(temperature, seconds, fahrenheit, preset)
        async with self._operation_lock:
            return await self._configure(settings, recipe_id)

    async def _configure(self, settings: dict[str, Any], recipe_id: str | None = None) -> Status:
        state = await self.status()
        if state.state in {"cooking", "pause"}:
            raise CommandError("Use update_settings for an active or paused cook")
        if state.error:
            raise CommandError(f"Appliance reports error {state.error}")
        if self._mqtt and state.state == "standby":
            await self._write({"status": "idle"})
            await self._wait_state({"idle"})
        data = {**settings, "status": "setting"}
        if recipe_id is not None:
            if not recipe_id:
                raise ValueError("recipe_id cannot be empty")
            data.update(recipe_id=recipe_id, step_id="")
            if self._mqtt:
                data.pop("preset")
        await self._write(data, recipe=recipe_id is not None)
        state = await self._wait_state({"setting"})
        # Do not start on previously configured settings after a silently ignored write.
        for name in ("temp", "time", "temp_unit"):
            if state.raw.get(name) != settings[name]:
                raise CommandError(f"Device did not confirm configured {name}; cooking was not started")
        if recipe_id is None and state.preset != settings["preset"]:
            raise CommandError("Device did not confirm selected preset; cooking was not started")
        return state

    async def start_cooking(self, temperature: int, seconds: int, *,
                            fahrenheit: bool = False, preset: int = 0,
                            recipe_id: str | None = None) -> Status:
        settings = cooking_settings(temperature, seconds, fahrenheit, preset)
        async with self._operation_lock:
            state = await self._configure(settings, recipe_id)
            if state.drawer_open is not False:
                raise CommandError("Drawer closure is not confirmed; cooking was not started")
            await self._write({"status": "cooking"})
            return await self._wait_state({"cooking"})

    async def pause(self) -> Status:
        async with self._operation_lock:
            await self.status()  # Wakes a parked FUSION controller first.
            await self._write({"status": "pause"})
            return await self._wait_state({"pause"})

    async def resume(self) -> Status:
        async with self._operation_lock:
            state = await self.status()
            if state.state != "pause" or state.drawer_open is not False:
                raise CommandError("Resume requires a paused cook and a confirmed closed drawer")
            if state.error:
                raise CommandError(f"Appliance reports error {state.error}")
            await self._write({"status": "cooking"})
            return await self._wait_state({"cooking"})

    async def stop(self) -> Status:
        async with self._operation_lock:
            await self.status()  # Wakes a parked FUSION controller first.
            await self._write({"status": "standby"})
            return await self._wait_state({"standby"})

    async def update_settings(self, *, temperature: int | None = None,
                              seconds: int | None = None,
                              remaining_seconds: int | None = None) -> Status:
        async with self._operation_lock:
            state = await self.status()
            if state.fahrenheit is None:
                raise CommandError("Device temperature unit is unknown")
            if temperature is None and seconds is None and remaining_seconds is None:
                raise ValueError("Provide temperature, seconds, or remaining_seconds")
            if seconds is not None and remaining_seconds is not None:
                raise ValueError("Choose total duration or remaining duration, not both")
            if remaining_seconds is not None and self._mqtt:
                # The SPECTRE FUSION Control port has no cur_time property;
                # writing it is refused with NCP port_error (8).
                raise ValueError("Over the cloud connection only the total cook time can be changed, "
                                 "not the remaining time")
            validated = cooking_settings(
                temperature if temperature is not None else state.temperature,
                seconds if seconds is not None else state.duration_seconds,
                state.fahrenheit, state.preset or 0)
            data = {key: value for key, value in validated.items()
                    if key == "temp_unit" or (key == "temp" and temperature is not None)
                    or (key == "time" and seconds is not None)}
            if remaining_seconds is not None:
                cooking_settings(state.temperature, remaining_seconds, state.fahrenheit, state.preset or 0)
                data["cur_time"] = remaining_seconds
            written_at = time.monotonic()
            await self._write(data)
            updated = await self.status()
            elapsed = math.ceil(time.monotonic() - written_at) + 1
            mismatch = any(
                not (type(updated.raw.get(key)) is int
                     and max(0, value - elapsed) <= updated.raw[key] <= value)
                if key == "cur_time" and updated.state == "cooking"
                else updated.raw.get(key) != value
                for key, value in data.items()
            )
            if mismatch:
                raise CommandError("Updated settings were acknowledged but not confirmed by status")
            return updated

    async def keep_warm(self, seconds: int = 1800) -> Status:
        return await self.start_cooking(80, seconds, preset=8)

    async def watch(self, interval: float = 5) -> AsyncIterator[Status]:
        if not math.isfinite(interval) or interval < 1:
            raise ValueError("Polling interval must be finite and at least one second")
        while True:
            # Monitoring must not wake a parked appliance.
            yield await self.status(wake=False)
            await asyncio.sleep(interval)

    async def monitor_job(self, interval: float = 5, timeout: float = 7200) -> Status:
        """Wait for an observed cook to finish; a standby transition is a stop."""
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        started = time.monotonic()
        observed_active = False
        async for state in self.watch(interval):
            if state.error:
                raise CommandError(f"Appliance reports error {state.error}")
            observed_active |= state.state in {"cooking", "pause"}
            if observed_active and state.state in {"finish", "standby"}:
                return state
            if time.monotonic() - started >= timeout:
                raise TimeoutError("Cooking monitor timed out; cooking was not stopped")

    async def device_info(self) -> dict[str, Any]:
        if self._mqtt:
            state = self._mqtt.device_state
            return {key: value for key, value in state.properties.items()
                    if not key.startswith("_homeid_")} if state else {}
        info = await self._api.get_device_info(self._device)
        firmware = await self._api.get_firmware_info(self._device)
        if info is None:
            raise CommandError("Device metadata unavailable")
        return {"device": info, "firmware": firmware}
