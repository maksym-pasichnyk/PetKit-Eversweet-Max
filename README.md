# PetKit Eversweet Max

Effortlessly connect, control, and monitor your PetKit Eversweet Max fountain in Home Assistant with this fully local Bluetooth integration. It talks directly to CTW3-family devices over BLE, exposes native Home Assistant entities and services, and keeps everyday control and telemetry out of the PetKit cloud.

## Features

- **Local BLE integration:** Direct communication with the fountain, no cloud required for normal operation.
- **Automatic discovery:** Detects nearby CTW3 devices that advertise as `Petkit_CTW3*`.
- **Core controls:** Toggle power, pause, lamp ring, and do-not-disturb.
- **Mode selection:** Switch between Standard, Intermittent, and Battery modes.
- **Advanced settings:** Adjust Smart/Battery work and sleep timings, lamp brightness, child lock, and inductive sensors on supported firmware.
- **Rich monitoring:** Track battery level, battery/DC voltage, filter remaining, pump runtime, firmware, uptime, restart count, and last drink timestamp.
- **Warnings and status:** Surface lack of water, low battery, filter replacement, breakdown, running state, night DND, DC power, and pet detection.
- **Maintenance and automation:** Reset the filter from Home Assistant, sync drinking history, and write lamp/DND schedules.

## Requirements

- Home Assistant `2024.12.0` or newer
- A working Bluetooth adapter available to Home Assistant
- A PetKit CTW3-family fountain within BLE range
- The device's 8-byte auth secret (`16` hex characters)

## Installation

1. Copy `custom_components/eversweet_ctw3` into your Home Assistant config directory under `custom_components/`.
2. Restart Home Assistant.
3. Open **Settings -> Devices & services -> Add Integration**.
4. Add **PetKit Eversweet Max**, or wait for Bluetooth discovery to offer it automatically.
5. Select the discovered `Petkit_CTW3*` device.
6. Enter the fountain's `16`-character hex secret during setup.

## Authentication

The fountain uses an 8-byte security value for the BLE security check (`cmd 86`).

- Enter the real secret during setup.
- If authentication fails, verify that the secret matches the one issued during PetKit app binding.
- The integration does not retrieve this value automatically, so you will need it from your existing PetKit setup before adding the device to Home Assistant.

After setup, day-to-day control and polling stay local over BLE.

## Entities

- **Switches:** Power, Pause, Lamp ring, Do-not-disturb, Child lock, Smart inductive sensor, Battery inductive sensor
- **Select:** Standard, Intermittent, Battery
- **Sensors:** Battery, Battery voltage, DC supply voltage, Filter remaining, Pump runtime today, Pump runtime total, Mode, Run status, Module status, Firmware, Last drink, Restart count, Uptime, Pump cycles
- **Binary sensors:** Lack of water, Low battery, Replace filter, Breakdown, Night DND active, DC connected, Running, Pet detected
- **Buttons:** Reset filter, Sync drinking history
- **Numbers:** Smart mode work time, Smart mode sleep time, Battery mode work time, Battery mode sleep time, Lamp brightness

## Services

- `eversweet_ctw3.write_light_schedule`: Overwrite the lamp-ring schedule
- `eversweet_ctw3.write_dnd_schedule`: Overwrite the do-not-disturb schedule
- `eversweet_ctw3.sync_history`: Pull drinking history records from the fountain

### Example

```yaml
service: eversweet_ctw3.write_dnd_schedule
data:
  device_id: <device-id>
  enabled: true
  entries:
    - start: 1320
      end: 480
      weekday_mask: 127
```

`start` and `end` are minutes of day, while `weekday_mask` uses PetKit's bitmask format where bit `0` is Monday and bit `6` is Sunday.

## Caveats

- `child_lock` is available only when `hardware + firmware / 100 >= 1.35`.
- `smart_inductive` and `battery_inductive` require firmware `>= 89`.
- The device rate-limits BLE notifications; keeping the poll interval at `30s` or more is recommended.
- OTA is intentionally not exposed by this integration.

## Tested Devices

- **EverSweet Max 2 (UVC)**

Bluetooth discovery also targets devices advertising as `Petkit_CTW3`, `Petkit_CTW3_2`, `Petkit_CTW3_100`, `Petkit_CTW3UV`, and `Petkit_CTW3UV_100`.