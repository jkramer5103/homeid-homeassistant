"""Config flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from custom_components.homeid_airfryer.config_flow import CloudAuthError
from custom_components.homeid_airfryer.const import CONF_DEVICE, DOMAIN
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

APPLIANCE = {"name": "Airfryer 5000 Series XXL", "macAddress": "aa:bb:cc:dd:ee:ff",
             "externalDeviceId": "ext-123", "id": "app-1"}


@pytest.fixture
def cloud():
    api = AsyncMock()
    api.request_otp.return_value = "vtoken"
    api.verify_otp.return_value = "session"
    api.get_oidc_tokens.return_value = {"access_token": "access", "refresh_token": "refresh-1"}
    api.get_appliances_via_homeid.return_value = [APPLIANCE]
    api.get_thing_name.return_value = "da-thing"
    with patch("custom_components.homeid_airfryer.config_flow.PhilipsCloudAPI", return_value=api):
        yield api


async def _login(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"email": "user@example.com"})
    assert result["step_id"] == "code"
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"code": " 123456 "})


async def test_cloud_flow_creates_entry(hass, cloud, fake_airfryer):
    result = await _login(hass)
    assert result["step_id"] == "appliance"
    with patch("custom_components.homeid_airfryer.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {
            "appliance": "ext-123", "model": "HD9285", "transport": "fusion"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    device = result["data"][CONF_DEVICE]
    assert device["transport"] == "fusion"
    assert device["thing_name"] == "da-thing"
    assert device["refresh_token"] == "refresh-1"
    assert result["result"].unique_id == "ext-123"
    cloud.verify_otp.assert_awaited_with("user@example.com", "123456", "vtoken")


async def test_bad_code_shows_error(hass, cloud, fake_airfryer):
    cloud.verify_otp.side_effect = CloudAuthError("bad code")
    result = await _login(hass)
    assert result["step_id"] == "code"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_local_without_credentials_is_rejected(hass, cloud, fake_airfryer):
    result = await _login(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "appliance": "ext-123", "model": "HD9285", "transport": "local", "host": "192.168.1.50"})
    assert result["errors"] == {"base": "no_local_credentials"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "appliance": "ext-123", "model": "HD9285", "transport": "local", "host": ""})
    assert result["errors"] == {"host": "host_required"}


async def test_offline_appliance_shows_error(hass, cloud, fake_airfryer):
    from custom_components.homeid_airfryer.homeid import CommandError

    fake_airfryer.fail_with = CommandError("offline")
    result = await _login(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {
        "appliance": "ext-123", "model": "HD9285", "transport": "fusion"})
    assert result["errors"] == {"base": "cannot_connect_device"}


async def test_reauth_updates_refresh_token(hass, cloud, fake_airfryer, config_entry):
    cloud.get_oidc_tokens.return_value = {"access_token": "a", "refresh_token": "refresh-new"}
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"email": "user@example.com"})
    with patch("custom_components.homeid_airfryer.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "1"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_DEVICE]["refresh_token"] == "refresh-new"
