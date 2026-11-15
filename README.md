# Philips HomeID Airfryer for Home Assistant

Custom integration for Philips HomeID **5000 Series XXL / HD9285** airfryers
(SPECTRE platform; HD9280 and HD9255 are also accepted). It wraps the
[homeid-python](https://github.com/jkramer5103/homeid-python) client, which is
bundled, so no extra package needs to be published.

Supported connections:

- **Cloud (FUSION MQTT):** for appliances migrated to HomeID FUSION. This needs internet access.
- **Local network:** HTTPS, or HTTP with AES, for appliances whose account record has local credentials.

## Install

### HACS (custom repository)

1. HACS → ⋮ → *Custom repositories* → add this repository's URL, category *Integration*.
2. Install **Philips HomeID Airfryer**, then restart Home Assistant.

### Manual

Copy `custom_components/homeid_airfryer` into your Home Assistant
`config/custom_components/` directory, then restart.

## Setup

*Settings → Devices & services → Add integration → Philips HomeID Airfryer*

1. Enter the email of the HomeID account your airfryer is already paired with.
2. Enter the code that HomeID emails you.
3. Pick the appliance, its model, and the connection type. For a local
   connection, also enter its LAN IP address. Tick *HTTP with AES* if
   discovery reports `https=0`.

The flow connects once to confirm that the appliance responds. When the
HomeID login expires, Home Assistant asks you to log in again (reauth). Rotated
refresh tokens are stored in the config entry automatically.

Each login creates its own token chain. Do not copy one refresh token into
several clients (e.g. this integration and the `homeid` CLI): a client that
rotates the token can invalidate the other's copy.

## Entities

| Entity | Purpose |
| --- | --- |
| `sensor.*_state` | `standby`, `idle`, `setting`, `cooking`, `pause`, `finish` |
| `sensor.*_remaining_time`, `sensor.*_total_cook_time` | Timer reported by the appliance |
| `sensor.*_target_temperature`, `sensor.*_active_program` | Current settings |
| `sensor.*_error_code` (diagnostic), `binary_sensor.*_problem` | Appliance error reporting |
| `binary_sensor.*_drawer`, `binary_sensor.*_cooking` | Drawer open; cook running or paused |
| `number.*_temperature`, `number.*_cook_time`, `select.*_program` | Settings for the next **Start** |
| `button.*_start`, `*_pause`, `*_resume`, `*_stop` | Controls |

The temperature and cook-time numbers stage values for the next start. When a
cook is active or paused, changing them updates the running cook:
temperature is changed, and cook time sets the remaining countdown.
Selecting the *Keep warm* program starts keep warm at 80 °C for up to 30
minutes.

Every command is confirmed by the appliance's reported state, not just by the
acknowledgement. Start checks that the drawer is closed. A failed or
unconfirmed command raises an error in the UI. Check the state before
retrying.

## Services

All services return the confirmed status as response data.

```yaml
action: homeid_airfryer.start_cooking
data:
  device_id: <airfryer device id>
  temperature: 180        # 40–200 °C (104–400 °F with fahrenheit: true)
  duration: "00:15:00"    # 1–60 minutes
  preset: fresh_fries     # optional built-in program
  # recipe_id: ABC123     # optional HomeID custom preset short ID
```

```yaml
action: homeid_airfryer.update_settings   # active or paused cook
data:
  device_id: <airfryer device id>
  temperature: 190
  remaining: "00:05:00"   # or duration: total cook time
```

```yaml
action: homeid_airfryer.keep_warm
data:
  device_id: <airfryer device id>
  duration: "00:20:00"    # up to 30 minutes
```

Example automation, to notify when food is ready:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.airfryer_state
    to: finish
actions:
  - action: notify.notify
    data:
      message: The airfryer is done.
```

## Polling

Local appliances are polled every 15 s. Cloud appliances are polled every 30 s
over the same MQTT connection. Each poll requests a fresh status, and cached
values are never reported as current. If the appliance is offline or
unplugged, its entities become unavailable until it reconnects.

## Validation status

Verified live on 2026-11-15 with an HD9285 (firmware 0.5.6) over FUSION in
Home Assistant 2026.2.3: setup, MQTT connection, and status/entity reporting.
The underlying client has also started a real cook (180 °C / 60 s). Pause,
resume, stop, settings changes, and keep warm are covered by tests against a
simulated client only.

## Development

```sh
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt ruff
.venv/bin/pytest -q
.venv/bin/ruff check .
```

To update the bundled client from a homeid-python checkout:

```sh
scripts/sync_library.sh /path/to/homeid-python
```

Licensing of the bundled protocol code: see [third-party notices](THIRD_PARTY_NOTICES.md).
