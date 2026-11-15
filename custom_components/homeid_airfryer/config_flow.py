"""Config flow: HomeID emailed-code login, appliance selection, connection type."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_DEVICE,
    CONF_EMAIL,
    CONF_TRANSPORT,
    CONF_USE_HTTP,
    DOMAIN,
    TRANSPORT_CLOUD,
    TRANSPORT_LOCAL,
)
from .homeid import Airfryer, CommandError, DeviceConfig
from .homeid._vendor.cloud_api import PhilipsCloudAPI
from .homeid._vendor.cloud_auth import (
    CloudAuthError,
    CloudBackendError,
    CloudConnectionError,
    CloudNotRegisteredError,
)
from .homeid.credentials import appliance_id, from_appliance

_LOGGER = logging.getLogger(__name__)

CONF_CODE = "code"
CONF_APPLIANCE = "appliance"
CONF_MODEL = "model"
MODELS = ["HD9285", "HD9280", "HD9255"]


def _login_error(err: Exception) -> str:
    if isinstance(err, CloudNotRegisteredError):
        return "not_registered"
    if isinstance(err, CloudBackendError):
        return "backend_error"
    if isinstance(err, (CloudConnectionError, aiohttp.ClientError, TimeoutError)):
        return "cannot_connect"
    return "invalid_auth"


def _label(appliance: dict[str, Any]) -> str:
    name = appliance.get("name") or appliance.get("ctn") or "Appliance"
    mac = appliance.get("macAddress")
    return f"{name} ({mac})" if mac else name


class HomeIDConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in with the account already used in the HomeID app."""

    VERSION = 1

    def __init__(self) -> None:
        self._api: PhilipsCloudAPI | None = None
        self._email = ""
        self._vtoken = ""
        self._tokens: dict[str, Any] = {}
        self._appliances: dict[str, dict[str, Any]] = {}
        self._selected: dict[str, Any] = {}

    @property
    def api(self) -> PhilipsCloudAPI:
        if self._api is None:
            self._api = PhilipsCloudAPI()
        return self._api

    async def _close(self) -> None:
        if self._api is not None:
            await self._api.close()
            self._api = None

    def async_remove(self) -> None:
        """Close the HTTP session if the user abandons the flow."""
        if self._api is not None:
            self.hass.async_create_task(self._close())

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the HomeID account email and send a login code."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            try:
                self._vtoken = await self.api.request_otp(self._email)
            except (CloudAuthError, aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("OTP request failed: %s", err)
                errors["base"] = _login_error(err)
            else:
                return await self.async_step_code()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_EMAIL, default=self._email): TextSelector(
                TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="email"))}),
            errors=errors,
        )

    async def async_step_code(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Verify the emailed code and fetch the account's appliances."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                session = await self.api.verify_otp(self._email, user_input[CONF_CODE].strip(), self._vtoken)
                self._tokens = await self.api.get_oidc_tokens(session)
                if not self._tokens.get("refresh_token"):
                    raise CloudAuthError("Login returned no refresh token")
            except (CloudAuthError, aiohttp.ClientError, TimeoutError) as err:
                _LOGGER.debug("Code verification failed: %s", err)
                errors["base"] = _login_error(err)
            else:
                if self.source == "reauth":
                    return await self._finish_reauth()
                return await self.async_step_appliance()
        return self.async_show_form(
            step_id="code",
            data_schema=vol.Schema({vol.Required(CONF_CODE): str}),
            description_placeholders={"email": self._email},
            errors=errors,
        )

    async def async_step_appliance(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick the airfryer and how Home Assistant reaches it."""
        errors: dict[str, str] = {}
        if not self._appliances:
            try:
                found = await self.api.get_appliances_via_homeid(self._tokens)
            except (CloudAuthError, aiohttp.ClientError, TimeoutError) as err:
                await self._close()
                return self.async_abort(reason=_login_error(err))
            for appliance in found:
                appliance = {**appliance, "id": appliance_id(appliance)}
                key = appliance.get("externalDeviceId") or appliance["id"]
                if key:
                    self._appliances[key] = appliance
            if not self._appliances:
                await self._close()
                return self.async_abort(reason="no_appliances")

        if user_input is not None:
            key = user_input[CONF_APPLIANCE]
            await self.async_set_unique_id(key)
            self._abort_if_unique_id_configured()
            host = user_input.get(CONF_HOST, "").strip()
            local = user_input[CONF_TRANSPORT] == TRANSPORT_LOCAL
            if local and not host:
                errors[CONF_HOST] = "host_required"
            else:
                try:
                    config = await self._build_config(
                        self._appliances[key], user_input[CONF_MODEL], host if local else "",
                        not user_input.get(CONF_USE_HTTP, False))
                    await self._test(config)
                except (TypeError, ValueError) as err:
                    _LOGGER.debug("Invalid appliance configuration: %s", err)
                    errors["base"] = "no_local_credentials" if local else "unsupported"
                except CloudAuthError as err:
                    errors["base"] = _login_error(err)
                except (CommandError, aiohttp.ClientError, OSError, TimeoutError) as err:
                    _LOGGER.debug("Appliance connection test failed: %s", err)
                    errors["base"] = "cannot_connect_device"
                else:
                    await self._close()
                    return self.async_create_entry(
                        title=self._appliances[key].get("name") or "Airfryer",
                        data={CONF_EMAIL: self._email, CONF_DEVICE: asdict(config)},
                    )

        options = [SelectOptionDict(value=key, label=_label(item)) for key, item in self._appliances.items()]
        schema = vol.Schema({
            vol.Required(CONF_APPLIANCE, default=options[0]["value"]): SelectSelector(
                SelectSelectorConfig(options=options, mode=SelectSelectorMode.DROPDOWN)),
            vol.Required(CONF_MODEL, default=MODELS[0]): SelectSelector(
                SelectSelectorConfig(options=MODELS, mode=SelectSelectorMode.DROPDOWN)),
            vol.Required(CONF_TRANSPORT, default=TRANSPORT_CLOUD): SelectSelector(
                SelectSelectorConfig(options=[TRANSPORT_CLOUD, TRANSPORT_LOCAL],
                                     translation_key=CONF_TRANSPORT)),
            vol.Optional(CONF_HOST, default=""): str,
            vol.Optional(CONF_USE_HTTP, default=False): bool,
        })
        return self.async_show_form(step_id="appliance", data_schema=schema, errors=errors)

    async def _build_config(self, appliance: dict[str, Any], model: str, host: str,
                            use_https: bool) -> DeviceConfig:
        """Mirror `homeid setup`: resolve the FUSION thing name when needed."""
        appliance = {**appliance, "ctn": appliance.get("ctn") or model}
        thing_name = ""
        if not host or not (appliance.get("clientId") and appliance.get("clientSecret")):
            thing_name = await self.api.get_thing_name(
                self._tokens["access_token"],
                appliance.get("externalDeviceId") or appliance.get("id", ""),
                appliance.get("macAddress", "")) or ""
        config = from_appliance(appliance, host=host, use_https=use_https,
                                refresh_token=self._tokens["refresh_token"], thing_name=thing_name)
        if host and config.transport != TRANSPORT_LOCAL:
            raise ValueError("Account has no local credentials for this appliance")
        return config

    async def _test(self, config: DeviceConfig) -> None:
        """Connect once; token rotation during the test updates `config`."""

        def keep(updated: DeviceConfig) -> None:
            config.refresh_token = updated.refresh_token
            config.encryption_key = updated.encryption_key

        async with Airfryer(config, keep):
            pass

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Refresh token was rejected; log in again."""
        self._email = entry_data.get(CONF_EMAIL, "")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Send a new code to the account email."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            try:
                self._vtoken = await self.api.request_otp(self._email)
            except (CloudAuthError, aiohttp.ClientError, TimeoutError) as err:
                errors["base"] = _login_error(err)
            else:
                return await self.async_step_code()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_EMAIL, default=self._email): str}),
            errors=errors,
        )

    async def _finish_reauth(self) -> ConfigFlowResult:
        await self._close()
        entry = self._get_reauth_entry()
        device = {**entry.data[CONF_DEVICE], "refresh_token": self._tokens["refresh_token"]}
        return self.async_update_reload_and_abort(
            entry, data={**entry.data, CONF_EMAIL: self._email, CONF_DEVICE: device})
