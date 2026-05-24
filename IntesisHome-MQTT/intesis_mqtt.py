import os
import sys
import asyncio
import json
import paho.mqtt.client as mqtt
from pyintesishome import IntesisHome

# =========================
# CONFIG FROM ENVIRONMENT VARIABLES
# =========================
INTESIS_USER   = os.getenv("INTESIS_USER")
INTESIS_PASS   = os.getenv("INTESIS_PASS")
MQTT_HOST      = os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT      = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER      = os.getenv("MQTT_USER")
MQTT_PASS      = os.getenv("MQTT_PASS")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", 30))
# Set to "F" for Fahrenheit; anything else defaults to Celsius
TEMP_UNIT      = os.getenv("TEMP_UNIT", "C").strip().upper()

if not INTESIS_USER or not INTESIS_PASS:
    print("❌ Fatal: INTESIS_USER / INTESIS_PASS environment variables are not set.")
    sys.exit(1)

controller   = None
loop         = None
command_lock = False

# Cache of detected modes per device so we only query once at startup
_device_mode_cache: dict[str, list[str]] = {}

# =========================
# INTESIS → HA MODE MAPPING
# =========================
INTESIS_TO_HA_MODE: dict[str, str] = {
    "cool":     "cool",
    "heat":     "heat",
    "dry":      "dry",
    "fan":      "fan_only",
    "fan_only": "fan_only",
    "auto":     "auto",
    "off":      "off",
}

# Reverse map for sending commands back to Intesis
HA_TO_INTESIS_MODE: dict[str, str] = {
    "cool":     "cool",
    "heat":     "heat",
    "dry":      "dry",
    "fan_only": "fan",
    "auto":     "auto",
}

# =========================
# TEMPERATURE HELPERS
# =========================
def c_to_f(celsius: float) -> int:
    return round(celsius * 9 / 5 + 32)

def f_to_c(fahrenheit: float) -> int:
    return round((fahrenheit - 32) * 5 / 9)

def to_display_temp(celsius_value) -> int | None:
    if celsius_value is None:
        return None
    val = float(celsius_value)
    return c_to_f(val) if TEMP_UNIT == "F" else round(val)

def to_intesis_temp(display_value) -> int:
    val = int(round(float(display_value)))
    return f_to_c(val) if TEMP_UNIT == "F" else val

# =========================
# DYNAMIC MODE DETECTION
# =========================
def _detect_modes_from_device_info(device_id: str) -> list[str]:
    """
    Try every known pyintesishome API surface to extract supported modes.
    Returns a list of HA-compatible mode strings (always includes 'off').
    Falls back to a safe default set on any failure.
    """
    DEFAULT_MODES = ["off", "cool", "heat", "dry", "fan_only", "auto"]

    raw_modes: list[str] = []

    # --- Strategy 1: explicit get_mode_list() method ---
    try:
        if hasattr(controller, "get_mode_list"):
            result = controller.get_mode_list(device_id)
            if result and isinstance(result, list):
                raw_modes = [str(m) for m in result]
    except Exception as exc:
        print(f"   ↳ get_mode_list() failed: {exc}")

    # --- Strategy 2: raw device dict ---
    if not raw_modes:
        try:
            devices = controller.get_devices()
            info    = devices.get(str(device_id), {})

            # Different library versions use different key names
            for key in ("availableModes", "modes", "supportedModes", "mode"):
                value = info.get(key)
                if isinstance(value, list) and value:
                    raw_modes = [str(m) for m in value]
                    break
                # Some versions store as a dict {id: name}
                if isinstance(value, dict) and value:
                    raw_modes = [str(v) for v in value.values()]
                    break
        except Exception as exc:
            print(f"   ↳ device dict scan failed: {exc}")

    # --- Strategy 3: get_setpoint_limits / get_operating_modes ---
    if not raw_modes:
        for method_name in ("get_operating_modes", "get_available_modes"):
            try:
                method = getattr(controller, method_name, None)
                if method:
                    result = method(device_id)
                    if result and isinstance(result, list):
                        raw_modes = [str(m) for m in result]
                        break
            except Exception as exc:
                print(f"   ↳ {method_name}() failed: {exc}")

    if not raw_modes:
        print(f"   ↳ No mode data found — using default set")
        return DEFAULT_MODES

    # Map raw Intesis names → HA names, always prepend 'off'
    ha_modes: list[str] = ["off"]
    for m in raw_modes:
        ha_name = INTESIS_TO_HA_MODE.get(m.lower())
        if ha_name and ha_name != "off" and ha_name not in ha_modes:
            ha_modes.append(ha_name)

    if len(ha_modes) < 2:
        print(f"   ↳ Mapping produced no usable modes — using default set")
        return DEFAULT_MODES

    return ha_modes


def get_ha_modes(device_id: str) -> list[str]:
    """Return cached HA modes for a device, detecting on first call."""
    if device_id not in _device_mode_cache:
        print(f"🔍 Detecting supported modes for device {device_id}...")
        modes = _detect_modes_from_device_info(device_id)
        _device_mode_cache[device_id] = modes
        print(f"   ✔ Modes resolved: {modes}")
    return _device_mode_cache[device_id]


# =========================
# MQTT CLIENT
# =========================
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
if MQTT_USER and MQTT_PASS:
    client.username_pw_set(MQTT_USER, MQTT_PASS)

# =========================
# INTESIS COMMAND HANDLER
# =========================
async def handle_command(device_id: str, command: str, payload: str):
    global command_lock
    try:
        val       = payload.strip().lower()
        base      = f"intesis/{device_id}/state"
        command_lock = True

        # ---- Power ----
        if command == "power":
            client.publish(f"{base}/power", val.upper(), retain=True)
            client.publish(f"{base}/mode", "off" if val == "off" else "auto", retain=True)
            if val == "on":
                await controller.set_power_on(device_id)
            else:
                await controller.set_power_off(device_id)

        # ---- Mode ----
        elif command == "mode":
            supported = get_ha_modes(device_id)

            if val not in supported and val != "off":
                print(f"⚠️  Mode '{val}' not supported by {device_id} (supported: {supported}). Ignoring.")
                return

            client.publish(f"{base}/mode", val, retain=True)
            client.publish(f"{base}/power", "OFF" if val == "off" else "ON", retain=True)

            if val == "off":
                await controller.set_power_off(device_id)
            else:
                print(f"🔌 Sending Power ON to {device_id}...")
                await controller.set_power_on(device_id)
                await asyncio.sleep(1.5)

                intesis_mode = HA_TO_INTESIS_MODE.get(val)
                if intesis_mode is None:
                    print(f"⚠️  No Intesis mapping for HA mode '{val}'. Skipping mode set.")
                else:
                    print(f"❄  Setting mode → {intesis_mode} (HA: {val})")
                    mode_setters = {
                        "cool": controller.set_mode_cool,
                        "heat": getattr(controller, "set_mode_heat", None),
                        "dry":  controller.set_mode_dry,
                        "fan":  controller.set_mode_fan,
                        "auto": controller.set_mode_auto,
                    }
                    setter = mode_setters.get(intesis_mode)
                    if setter:
                        await setter(device_id)
                    else:
                        print(f"⚠️  No setter found for Intesis mode '{intesis_mode}'")

        # ---- Temperature ----
        elif command == "temperature":
            display_temp  = int(round(float(payload)))
            intesis_temp  = to_intesis_temp(payload)
            client.publish(f"{base}/temperature", str(display_temp), retain=True)
            print(f"🌡  Temperature: {display_temp}°{TEMP_UNIT} → {intesis_temp}°C sent to Intesis")
            await controller.set_temperature(device_id, intesis_temp)

        # ---- Fan speed ----
        elif command == "fan":
            client.publish(f"{base}/fan", val, retain=True)
            await controller.set_fan_speed(device_id, val)

        else:
            print(f"⚠️  Unknown command '{command}' for {device_id}. Ignoring.")
            return

        print(f"✔  Command complete: {device_id} | {command} → {payload}")
        await asyncio.sleep(2.5)
        await publish_state(device_id)

    except Exception as exc:
        print(f"❌ Command error on {device_id} ({command}): {exc}")
    finally:
        command_lock = False


# =========================
# MQTT CALLBACKS
# =========================
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✔  Connected to MQTT broker.")
        client.subscribe("intesis/+/set/#")
    else:
        print(f"❌ MQTT connection failed — code {reason_code}")


def on_message(client, userdata, msg):
    global loop
    topic   = msg.topic
    payload = msg.payload.decode()
    print(f"📩 MQTT in: {topic} → {payload}")

    parts = topic.split("/")
    # Expected: intesis / <device_id> / set / <command>
    if len(parts) < 4:
        return

    device_id = parts[1]
    command   = parts[3]
    asyncio.run_coroutine_threadsafe(
        handle_command(device_id, command, payload), loop
    )


# =========================
# PUBLISH STATE
# =========================
async def publish_state(device_id: str):
    try:
        power   = controller.get_power_state(device_id)
        mode    = controller.get_mode(device_id)
        setpoint = controller.get_setpoint(device_id)    # always °C from Intesis
        ambient  = controller.get_temperature(device_id) # always °C from Intesis
        fan      = controller.get_fan_speed(device_id)

        base = f"intesis/{device_id}/state"
        is_on = power in [True, "on", "ON", 1]

        client.publish(f"{base}/power", "ON" if is_on else "OFF", retain=True)

        ha_mode = str(mode).lower() if is_on else "off"
        if ha_mode == "fan":
            ha_mode = "fan_only"
        client.publish(f"{base}/mode", ha_mode, retain=True)

        if setpoint is not None:
            client.publish(f"{base}/temperature", str(to_display_temp(setpoint)), retain=True)

        if ambient is not None:
            client.publish(f"{base}/current_temperature", str(to_display_temp(ambient)), retain=True)

        if fan:
            client.publish(f"{base}/fan", str(fan).lower(), retain=True)

    except Exception as exc:
        print(f"❌ State publish error for {device_id}: {exc}")


# =========================
# PUBLISH DISCOVERY
# =========================
async def publish_discovery(device_id: str, name: str):
    topic = f"homeassistant/climate/{device_id}/config"

    # Temperature range in display unit
    temp_min = c_to_f(16) if TEMP_UNIT == "F" else 16   # 61°F / 16°C
    temp_max = c_to_f(30) if TEMP_UNIT == "F" else 30   # 86°F / 30°C

    # ✅ Dynamically resolved from cloud
    ha_modes = get_ha_modes(device_id)

    payload = {
        "name":          name,
        "uniq_id":       f"intesis_{device_id}",
        "object_id":     f"intesis_{device_id}",
        "temperature_unit": TEMP_UNIT,

        "mode_cmd_t":    f"intesis/{device_id}/set/mode",
        "mode_stat_t":   f"intesis/{device_id}/state/mode",
        "temp_cmd_t":    f"intesis/{device_id}/set/temperature",
        "temp_stat_t":   f"intesis/{device_id}/state/temperature",
        "curr_temp_t":   f"intesis/{device_id}/state/current_temperature",
        "fan_mode_cmd_t": f"intesis/{device_id}/set/fan",
        "fan_mode_stat_t": f"intesis/{device_id}/state/fan",
        "pow_cmd_t":     f"intesis/{device_id}/set/power",
        "pow_stat_t":    f"intesis/{device_id}/state/power",

        "modes":         ha_modes,
        "fan_modes":     ["quiet", "low", "medium", "high", "auto"],
        "temp_min":      temp_min,
        "temp_max":      temp_max,
        "temp_step":     1,

        "device": {
            "identifiers": [f"intesis_{device_id}"],
            "name":         name,
            "manufacturer": "Intesis",
            "model":        "IntesisHome AC Bridge",
        },
    }

    client.publish(topic, json.dumps(payload), retain=True)
    print(f"📡 Discovery published: {name} | modes={ha_modes} | unit=°{TEMP_UNIT}")


# =========================
# MAIN
# =========================
async def main():
    global controller, loop, command_lock
    loop = asyncio.get_running_loop()

    print(f"🌡  Temperature unit: °{TEMP_UNIT}")
    print("🔄 Connecting to IntesisHome Cloud...")

    controller = IntesisHome(INTESIS_USER, INTESIS_PASS)
    await controller.connect()

    devices = controller.get_devices()
    print(f"🏠 Devices found: {list(devices.keys())}")

    if not devices:
        print("❌ No devices returned from IntesisHome. Check credentials.")
        sys.exit(1)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"🌐 Connecting to MQTT at {MQTT_HOST}:{MQTT_PORT}...")
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()

    for device_id in devices:
        name = controller.get_device_name(device_id)
        # Mode detection happens here; result is cached for subsequent calls
        await publish_discovery(device_id, name)
        await publish_state(device_id)

    print("🚀 Intesis MQTT bridge running.")

    while True:
        try:
            if not command_lock:
                for device_id in devices:
                    await publish_state(device_id)
        except Exception as exc:
            print(f"⚠️  Status loop error: {exc}")
        await asyncio.sleep(UPDATE_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
