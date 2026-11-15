# Philips HomeID Airfryer for Home Assistant

Custom integration for Philips HomeID **5000 Series XXL / HD9285** airfryers
(SPECTRE platform; HD9280 and HD9255 are also accepted). Monitor and control
cooking from Home Assistant dashboards, automations, and scripts.

Supported connections:

- **Cloud (FUSION MQTT):** for appliances migrated to HomeID FUSION. This needs internet access.
- **Local network:** HTTPS, or HTTP with AES, for appliances whose account record has local credentials.

All required code is included. Only `paho-mqtt` is installed automatically by
Home Assistant.

## Before you start

- Home Assistant **2025.2 or newer** (Settings → About shows your version).
- The airfryer is already set up in the official **Philips HomeID app** and works there.
  This integration uses that same account. It does not pair new appliances.
- You can receive email at your HomeID account address (for the login code).
- The airfryer is plugged in and online while you set up the integration.

## Step 1: Install the integration

Choose **one** of the two options.

### Option A: HACS (recommended, gets updates)

You need [HACS](https://hacs.xyz/docs/use/) installed in Home Assistant.

1. Click this button, or follow steps 2–5 by hand:

   [![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jkramer5103&repository=homeid-homeassistant&category=integration)

2. In Home Assistant, open **HACS** in the sidebar.
3. Click the **⋮** menu (top right) → **Custom repositories**.
4. Enter `https://github.com/jkramer5103/homeid-homeassistant`, set **Type**
   to **Integration**, and click **Add**. Close the dialog.
5. Search HACS for **Philips HomeID Airfryer**, open it, and click **Download** → **Download**.
6. Restart Home Assistant: **Settings → System → ⏻ (top right) → Restart Home Assistant**.

### Option B: Manual copy

1. Download this repository: **Code → Download ZIP** on GitHub, then unzip it.
2. Open your Home Assistant configuration folder, the folder that contains
   `configuration.yaml`. You can use the *Samba share*, *Studio Code Server*, or
   *Terminal & SSH* add-on, or `/config` in a Docker install.
3. If there is no `custom_components` folder there, create it.
4. Copy the folder `custom_components/homeid_airfryer` from the ZIP into it, so
   that this file exists:

   ```text
   config/custom_components/homeid_airfryer/manifest.json
   ```

5. Restart Home Assistant: **Settings → System → ⏻ → Restart Home Assistant**.

## Step 2: Add your airfryer

1. Click this button, or go to **Settings → Devices & services → + Add integration**
   and search for **Philips HomeID Airfryer**:

   [![Add integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=homeid_airfryer)

   If it does not appear, the restart did not pick up the files. Check the
   path from Step 1, clear the browser cache, and restart again.

2. **HomeID account:** enter the email address you use in the HomeID app and click **Submit**.
3. **Enter login code:** HomeID emails you a code. Enter it and click **Submit**.
   The code expires after a few minutes. If it fails, close the dialog and start again.
4. **Select airfryer:**
   - **Appliance:** your airfryer, listed with its MAC address.
   - **Model:** the model on the type plate under the appliance (HD9285 for the 5000 Series XXL).
   - **Connection:**
     - **Cloud (FUSION):** use this unless you know otherwise. Leave the LAN address empty.
     - **Local network:** only if your account has local credentials for the appliance.
       Enter its IP address (find it in your router; give it a fixed/DHCP-reserved
       address). Tick **HTTP with AES** only for older appliances that do not use HTTPS.
5. Click **Submit**. Home Assistant connects once to check that the airfryer
   responds, then creates the **Airfryer** device. Assign an area if you want.

Your device is at **Settings → Devices & services → Philips HomeID Airfryer → 1 device**.
Click **Add to dashboard** on the device page to get a ready-made card.

### If setup fails

| Message | What to do |
| --- | --- |
| *Could not connect to the airfryer* | Plug it in, check it works in the HomeID app, then retry. |
| *The code or account was rejected* | Request a new code: close the dialog and start again. |
| *Not a fully registered HomeID account* | Open the HomeID app and finish registration/consents. |
| *No local credentials for this appliance* | Choose **Cloud (FUSION)** instead. |
| *No appliances were found* | Make sure you used the same email as in the HomeID app. |

When HomeID asks you to log in again later (Home Assistant shows a
**Repair / Reconfigure** notice), click it and enter a fresh emailed code. Your
entities and automations are kept.

Each login creates its own token chain. Do not copy one refresh token into
several clients (for example, this integration and the `homeid` CLI). A client
that rotates the token can invalidate the other's copy.

### Updating and removing

- **HACS:** when an update appears, click **Update** in HACS and restart.
- **Manual:** replace the `homeid_airfryer` folder and restart.
- **Remove:** Settings → Devices & services → Philips HomeID Airfryer → ⋮ → **Delete**.
  Then remove it in HACS (or delete the folder) and restart.

### Debug logging

For a bug report, add this to `configuration.yaml`, restart, and reproduce the
problem. Then open **Settings → System → Logs**. Diagnostics from the device page
(**Download diagnostics**) are safe to share: credentials are redacted.

```yaml
logger:
  logs:
    custom_components.homeid_airfryer: debug
```

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
cook is active or paused, changing them updates the running cook. Temperature
is changed directly. Cook time sets the remaining countdown on a local
connection. Over the cloud it sets the **total** cook time, because the
appliance's cloud control port has no remaining-time field.
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
  remaining: "00:05:00"   # local connection only; over the cloud use
                          # duration: total cook time
```

```yaml
action: homeid_airfryer.keep_warm
data:
  device_id: <airfryer device id>
  duration: "00:20:00"    # up to 30 minutes
```

Example automation, to notify when food is ready. Firmware 0.5.6 over FUSION
went from `cooking` straight to `idle` when the timer ran out, without
reporting `finish`, so the trigger accepts both. A stop goes to `standby`
instead, so this does not fire when you cancel a cook.

```yaml
triggers:
  - trigger: state
    entity_id: sensor.airfryer_state
    from: cooking
    to: [finish, idle]
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

When idle, some cloud appliances (HD9285 firmware 0.5.6) put their cooking
controller to sleep while Wi-Fi stays connected. A sleeping controller does
not answer status requests. Polling does not wake it. Instead, the state and
error come from the Philips cloud's latest report, and temperature, times,
program, and drawer show *unknown* until the next cook. Pressing a button or
changing a value wakes the appliance first. That first command can take up to
about 30 seconds.

## Validation status

Verified live on 2026-11-15 with an HD9285 (firmware 0.5.6) over FUSION in
Home Assistant 2026.2.3: setup, MQTT connection, and status/entity reporting.
Version 0.1.1 status reads were re-checked live against the same appliance.
Waking a sleeping controller is covered by simulated tests only.
The underlying client has also started a real cook (180 °C / 60 s). Pause,
resume, stop, settings changes, and keep warm are covered by tests against a
simulated client only.

## Development

```sh
python -m venv .venv && .venv/bin/pip install -r requirements_test.txt ruff
.venv/bin/pytest -q
.venv/bin/ruff check .
```

The appliance client in `custom_components/homeid_airfryer/homeid` is bundled from
the homeid-python project; `SOURCE` records the commit. To update it from a checkout:

```sh
scripts/sync_library.sh /path/to/homeid-python
```

Licensing of the bundled protocol code: see [third-party notices](THIRD_PARTY_NOTICES.md).

## License

[BSD 2-Clause](LICENSE). The bundled protocol code in
`custom_components/homeid_airfryer/homeid/_vendor` keeps its own BSD 2-Clause
license and copyright (Renaud Allard). See [third-party notices](THIRD_PARTY_NOTICES.md).

This project is not affiliated with or endorsed by Philips or Versuni.
