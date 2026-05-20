# IntesisHome MQTT Bridge — Home Assistant Add-on

A Home Assistant local add-on that connects **IntesisHome AC units** to Home Assistant via MQTT, enabling full climate control through the HA climate entity (mode, temperature, fan speed, power).

---

## Features

- Auto-discovers all IntesisHome devices linked to your account
- Publishes MQTT Discovery payloads so devices appear automatically in HA
- Supports: **power**, **mode** (cool / dry / fan only / auto / off), **temperature setpoint**, and **fan speed**
- Optimistic state updates for instant UI feedback
- Configurable polling interval for live state sync
- Safe command sequencing — power-on is always sent before a mode change

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Home Assistant OS or Supervised | Required to run add-ons |
| [Mosquitto Broker add-on](https://github.com/home-assistant/addons/tree/master/mosquitto) | Or any external MQTT broker |
| IntesisHome account | With at least one registered AC device |
| Python `pyintesishome` compatible device | IntesisHome WiFi or Box modules |

---

## Installation

### 1. Add this repository to Home Assistant

1. In Home Assistant go to **Settings → Add-ons → Add-on Store**
2. Click **⋮** (top-right menu) → **Repositories**
3. Paste the URL of this repository:
   ```
   https://github.com/Fahed-Alhammadi/home-assistant-addons
   ```
4. Click **Add**, then close the dialog
5. Scroll down to find **IntesisHome MQTT Bridge** and click **Install**

---

## Configuration

After installation, go to the **Configuration** tab of the add-on and fill in:

```yaml
intesis_user: "your@email.com"
intesis_pass: "your_intesis_password"
mqtt_host: "core-mosquitto"
mqtt_port: 1883
mqtt_user: "your_mqtt_user"
mqtt_pass: "your_mqtt_password"
update_interval: 30
```

| Option | Description | Default |
|---|---|---|
| `intesis_user` | IntesisHome account email | — |
| `intesis_pass` | IntesisHome account password | — |
| `mqtt_host` | MQTT broker hostname or IP | `core-mosquitto` |
| `mqtt_port` | MQTT broker port | `1883` |
| `mqtt_user` | MQTT username | — |
| `mqtt_pass` | MQTT password | — |
| `update_interval` | Seconds between state polls | `30` |

> **Tip:** If you are using the Mosquitto add-on, set `mqtt_host` to `core-mosquitto`. If using an external broker, use its IP address instead.

---

## Usage

Once the add-on is started:

1. Go to **Settings → Devices & Services → MQTT** — your AC units appear automatically as climate entities via MQTT Discovery
2. Control them from the HA dashboard, automations, or voice assistants as normal climate devices

### Supported Modes

| HA Mode | AC Action |
|---|---|
| `off` | Powers the unit off |
| `cool` | Cooling mode |
| `dry` | Dehumidify mode |
| `fan_only` | Fan only (no heating/cooling) |
| `auto` | Auto mode |

### Supported Fan Speeds

`quiet` · `low` · `medium` · `high` · `auto`

### Temperature Range

16 °C – 30 °C in 1 °C steps

---

## MQTT Topic Structure

| Topic | Direction | Description |
|---|---|---|
| `intesis/{device_id}/state/power` | Published | Current power state (`ON` / `OFF`) |
| `intesis/{device_id}/state/mode` | Published | Current mode |
| `intesis/{device_id}/state/temperature` | Published | Target setpoint |
| `intesis/{device_id}/state/current_temperature` | Published | Ambient room temperature |
| `intesis/{device_id}/state/fan` | Published | Current fan speed |
| `intesis/{device_id}/set/power` | Subscribe | Send `ON` or `OFF` |
| `intesis/{device_id}/set/mode` | Subscribe | Send mode string |
| `intesis/{device_id}/set/temperature` | Subscribe | Send target temp as number |
| `intesis/{device_id}/set/fan` | Subscribe | Send fan speed string |

---

## Troubleshooting

**Devices not appearing in Home Assistant**
- Make sure MQTT Integration is set up in HA (Settings → Devices & Services → Add Integration → MQTT)
- Check the add-on **Log** tab for connection errors
- Verify your IntesisHome credentials are correct

**Mode changes not applying**
- The add-on automatically sends a power-on command before changing mode with a 1.5 s delay — this is intentional to work around IntesisHome cloud sequencing requirements

**State not updating**
- Reduce `update_interval` for more frequent polling (minimum recommended: 15 seconds)
- Check your network connectivity to the IntesisHome cloud

**MQTT connection refused**
- Confirm your MQTT username and password are correct
- If using Mosquitto add-on, ensure the user is created under the Mosquitto add-on configuration

---

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

---

## License

[MIT](LICENSE)

---

## Acknowledgements

- [`pyintesishome`](https://github.com/jnimmo/pyintesishome) — Python library for the IntesisHome cloud API
- [`paho-mqtt`](https://github.com/eclipse/paho.mqtt.python) — MQTT client library
- [Home Assistant](https://www.home-assistant.io/) — Open source home automation platform
