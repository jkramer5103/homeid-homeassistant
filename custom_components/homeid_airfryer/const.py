"""Constants for the Philips HomeID Airfryer integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "homeid_airfryer"
MANUFACTURER: Final = "Philips"

CONF_DEVICE: Final = "device"
CONF_EMAIL: Final = "email"
CONF_TRANSPORT: Final = "transport"
CONF_USE_HTTP: Final = "use_http"

TRANSPORT_CLOUD: Final = "fusion"
TRANSPORT_LOCAL: Final = "local"

SCAN_INTERVAL_LOCAL: Final = timedelta(seconds=15)
SCAN_INTERVAL_CLOUD: Final = timedelta(seconds=30)

# Appliance states reported in the "status" property.
STATES: Final = ["standby", "idle", "setting", "cooking", "pause", "finish", "unknown"]
ACTIVE_STATES: Final = {"cooking", "pause"}

PRESETS: Final = {
    0: "manual",
    1: "frozen_snacks",
    2: "fresh_fries",
    3: "chicken_drumsticks",
    4: "fish",
    5: "cake",
    6: "meat_chops",
    7: "vegetables",
    8: "keep_warm",
}
PRESET_IDS: Final = {name: number for number, name in PRESETS.items()}

# HD9285 manual ranges, mirrored from homeid.client.cooking_settings.
MIN_TEMP_C: Final = 40
MAX_TEMP_C: Final = 200
MIN_TEMP_F: Final = 104
MAX_TEMP_F: Final = 400
MIN_SECONDS: Final = 60
MAX_SECONDS: Final = 3600
KEEP_WARM_MAX_SECONDS: Final = 1800

DEFAULT_TEMPERATURE: Final = 180
DEFAULT_SECONDS: Final = 900

SERVICE_START_COOKING: Final = "start_cooking"
SERVICE_UPDATE_SETTINGS: Final = "update_settings"
SERVICE_KEEP_WARM: Final = "keep_warm"

ATTR_TEMPERATURE: Final = "temperature"
ATTR_DURATION: Final = "duration"
ATTR_REMAINING: Final = "remaining"
ATTR_PRESET: Final = "preset"
ATTR_RECIPE_ID: Final = "recipe_id"
ATTR_FAHRENHEIT: Final = "fahrenheit"
