"""Entity, control, and service tests against a fake client."""

from __future__ import annotations

import pytest

from custom_components.homeid_airfryer.const import CONF_DEVICE, DOMAIN
from custom_components.homeid_airfryer.homeid import CommandError, Status
from custom_components.homeid_airfryer.homeid._vendor.cloud_auth import CloudAuthError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .conftest import make_status


async def _setup(hass, entry):
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_entities_reflect_status(hass, fake_airfryer, config_entry):
    fake_airfryer.status_value = make_status(status="cooking", cur_time=420, drawer_open=False, preset=2)
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get("sensor.airfryer_state").state == "cooking"
    assert hass.states.get("sensor.airfryer_remaining_time").state == "7.0"
    assert hass.states.get("sensor.airfryer_target_temperature").state == "180"
    assert hass.states.get("sensor.airfryer_active_program").state == "fresh_fries"
    assert hass.states.get("binary_sensor.airfryer_drawer").state == "off"
    assert hass.states.get("binary_sensor.airfryer_cooking").state == "on"
    assert hass.states.get("binary_sensor.airfryer_problem").state == "off"


async def test_start_button_uses_staged_settings(hass, fake_airfryer, config_entry):
    await _setup(hass, config_entry)
    await hass.services.async_call("number", "set_value",
                                   {ATTR_ENTITY_ID: "number.airfryer_temperature", "value": 160}, blocking=True)
    await hass.services.async_call("number", "set_value",
                                   {ATTR_ENTITY_ID: "number.airfryer_cook_time", "value": 12}, blocking=True)
    await hass.services.async_call("select", "select_option",
                                   {ATTR_ENTITY_ID: "select.airfryer_program", "option": "fish"}, blocking=True)
    client = fake_airfryer.instances[-1]
    assert client.calls == []  # Idle appliance: values are only staged.
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.airfryer_start"}, blocking=True)
    assert client.calls == [("start_cooking", (160, 720), {"preset": 4})]
    assert hass.states.get("sensor.airfryer_state").state == "cooking"


async def test_keep_warm_program(hass, fake_airfryer, config_entry):
    await _setup(hass, config_entry)
    await hass.services.async_call("select", "select_option",
                                   {ATTR_ENTITY_ID: "select.airfryer_program", "option": "keep_warm"}, blocking=True)
    await hass.services.async_call("number", "set_value",
                                   {ATTR_ENTITY_ID: "number.airfryer_cook_time", "value": 45}, blocking=True)
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.airfryer_start"}, blocking=True)
    assert fake_airfryer.instances[-1].calls == [("keep_warm", (1800,), {})]


async def test_setpoints_apply_live_while_cooking(hass, fake_airfryer, config_entry):
    fake_airfryer.status_value = make_status(status="cooking")
    await _setup(hass, config_entry)
    await hass.services.async_call("number", "set_value",
                                   {ATTR_ENTITY_ID: "number.airfryer_temperature", "value": 190}, blocking=True)
    await hass.services.async_call("number", "set_value",
                                   {ATTR_ENTITY_ID: "number.airfryer_cook_time", "value": 5}, blocking=True)
    assert fake_airfryer.instances[-1].calls == [
        ("update_settings", (), {"temperature": 190}),
        ("update_settings", (), {"seconds": 300}),
    ]


async def test_missed_poll_keeps_live_connection(hass, fake_airfryer, config_entry):
    await _setup(hass, config_entry)
    client = fake_airfryer.instances[-1]
    fake_airfryer.fail_with = CommandError("No fresh status from the appliance or the cloud shadow")
    await config_entry.runtime_data.async_refresh()
    assert not client.closed
    assert hass.states.get("sensor.airfryer_state").state == "unavailable"
    fake_airfryer.fail_with = None
    await config_entry.runtime_data.async_refresh()
    assert fake_airfryer.instances[-1] is client
    assert hass.states.get("sensor.airfryer_state").state == "idle"


async def test_sleeping_appliance_reports_shadow_state(hass, fake_airfryer, config_entry):
    fake_airfryer.status_value = Status(
        state="standby", temperature=None, fahrenheit=None, duration_seconds=None,
        remaining_seconds=None, drawer_open=None, preset=None, error=0,
        observed_at=0, raw={}, source="shadow")
    await _setup(hass, config_entry)
    assert hass.states.get("sensor.airfryer_state").state == "standby"
    assert hass.states.get("sensor.airfryer_target_temperature").state == "unknown"
    assert hass.states.get("binary_sensor.airfryer_problem").state == "off"


async def test_pause_stop_buttons(hass, fake_airfryer, config_entry):
    await _setup(hass, config_entry)
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.airfryer_pause"}, blocking=True)
    assert hass.states.get("sensor.airfryer_state").state == "pause"
    await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.airfryer_stop"}, blocking=True)
    assert hass.states.get("sensor.airfryer_state").state == "standby"


async def test_command_failure_raises(hass, fake_airfryer, config_entry):
    await _setup(hass, config_entry)
    client = fake_airfryer.instances[-1]

    async def refuse():
        raise CommandError("Resume requires a paused cook")

    client.resume = refuse
    with pytest.raises(HomeAssistantError, match="Resume requires"):
        await hass.services.async_call("button", "press", {ATTR_ENTITY_ID: "button.airfryer_resume"}, blocking=True)


async def test_services(hass, fake_airfryer, config_entry):
    await _setup(hass, config_entry)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, "ext-123")})
    response = await hass.services.async_call(DOMAIN, "start_cooking", {
        "device_id": device.id, "temperature": 200, "duration": {"minutes": 20}, "preset": "cake",
    }, blocking=True, return_response=True)
    assert response["state"] == "cooking"
    await hass.services.async_call(DOMAIN, "update_settings", {
        "device_id": device.id, "remaining": "00:03:00"}, blocking=True)
    await hass.services.async_call(DOMAIN, "keep_warm", {"device_id": device.id}, blocking=True)
    assert fake_airfryer.instances[-1].calls == [
        ("start_cooking", (200, 1200), {"fahrenheit": False, "preset": 5, "recipe_id": None}),
        ("update_settings", (), {"temperature": None, "seconds": None, "remaining_seconds": 180}),
        ("keep_warm", (1800,), {}),
    ]


async def test_rotated_token_is_persisted(hass, fake_airfryer, config_entry):
    await _setup(hass, config_entry)
    client = fake_airfryer.instances[-1]
    client.config.refresh_token = "refresh-2"
    client.save_config(client.config)
    assert config_entry.data[CONF_DEVICE]["refresh_token"] == "refresh-2"


async def test_offline_appliance_retries_setup(hass, fake_airfryer, config_entry):
    fake_airfryer.fail_with = CommandError("Airfryer is offline")
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_rejected_token_starts_reauth(hass, fake_airfryer, config_entry):
    fake_airfryer.fail_with = CloudAuthError("Token refresh rejected")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    assert any(flow["context"]["source"] == "reauth" for flow in hass.config_entries.flow.async_progress())


async def test_unload_closes_client(hass, fake_airfryer, config_entry):
    await _setup(hass, config_entry)
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert fake_airfryer.instances[-1].closed


async def test_diagnostics_redact_credentials(hass, fake_airfryer, config_entry):
    from custom_components.homeid_airfryer.diagnostics import async_get_config_entry_diagnostics

    await _setup(hass, config_entry)
    result = await async_get_config_entry_diagnostics(hass, config_entry)
    text = repr(result)
    assert "refresh-1" not in text and "user@example.com" not in text and "ext-123" not in text
    assert result["entry"]["device"]["transport"] == "fusion"
    assert result["status"]["state"] == "idle"
