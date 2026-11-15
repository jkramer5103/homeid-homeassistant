"""Shared fixtures: a fake airfryer client replaces network access."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, ClassVar
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.homeid_airfryer.const import CONF_DEVICE, CONF_EMAIL, DOMAIN
from custom_components.homeid_airfryer.homeid import DeviceConfig, Status


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components in every test."""
    return


def make_status(**properties: Any) -> Status:
    base = {"status": "idle", "temp": 180, "temp_unit": False, "time": 900, "cur_time": 900,
            "drawer_open": False, "preset": 0, "error": 0}
    return Status.from_properties({**base, **properties}, observed_at=0)


DEVICE = DeviceConfig(
    model="HD9285", device_id="ext-123", appliance_id="app-1", transport="fusion",
    refresh_token="refresh-1", thing_name="da-thing",
)


class FakeAirfryer:
    """Records commands and returns confirmed states, like the real client."""

    instances: ClassVar[list[FakeAirfryer]] = []
    status_value: Status = make_status()
    fail_with: BaseException | None = None

    def __init__(self, config: DeviceConfig, save_config=None) -> None:
        config.validate()
        self.config = config
        self.save_config = save_config
        self.calls: list[tuple[str, tuple, dict]] = []
        self.closed = False
        FakeAirfryer.instances.append(self)

    async def __aenter__(self):
        if FakeAirfryer.fail_with:
            raise FakeAirfryer.fail_with
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        self.closed = True

    async def status(self) -> Status:
        if FakeAirfryer.fail_with:
            raise FakeAirfryer.fail_with
        return FakeAirfryer.status_value

    def _record(self, name, *args, state="cooking", **kwargs) -> Status:
        self.calls.append((name, args, kwargs))
        FakeAirfryer.status_value = make_status(status=state)
        return FakeAirfryer.status_value

    async def start_cooking(self, *args, **kwargs):
        return self._record("start_cooking", *args, **kwargs)

    async def keep_warm(self, *args, **kwargs):
        return self._record("keep_warm", *args, **kwargs)

    async def pause(self):
        return self._record("pause", state="pause")

    async def resume(self):
        return self._record("resume")

    async def stop(self):
        return self._record("stop", state="standby")

    async def update_settings(self, **kwargs):
        return self._record("update_settings", **kwargs)

    async def device_info(self):
        return {"hostFirmwareVersion": "0.5.6"}


@pytest.fixture
def fake_airfryer():
    FakeAirfryer.instances = []
    FakeAirfryer.status_value = make_status()
    FakeAirfryer.fail_with = None
    with patch("custom_components.homeid_airfryer.coordinator.Airfryer", FakeAirfryer), \
         patch("custom_components.homeid_airfryer.config_flow.Airfryer", FakeAirfryer):
        yield FakeAirfryer


@pytest.fixture
def config_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="ext-123", title="Airfryer 5000 Series XXL",
        data={CONF_EMAIL: "user@example.com", CONF_DEVICE: asdict(DEVICE)},
    )
    entry.add_to_hass(hass)
    return entry
