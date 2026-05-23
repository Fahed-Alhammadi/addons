import os
import sys
import asyncio
import json
import paho.mqtt.client as mqtt
from pyintesishome import IntesisHome

# =========================
# CONFIG FROM ENVIRONMENTAL VARIABLES
# =========================
INTESIS_USER = os.getenv("INTESIS_USER")
INTESIS_PASS = os.getenv("INTESIS_PASS")
MQTT_HOST = os.getenv("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASS = os.getenv("MQTT_PASS")
UPDATE_INTERVAL = int(os.getenv("UPDATE_INTERVAL", 30))
# Set to "F" to work in Fahrenheit; any other value defaults to Celsius
TEMP_UNIT = os.getenv("TEMP_UNIT", "C").strip().upper()

if not INTESIS_USER or not INTESIS_PASS:
    print("❌ Fatal Configuration Error: Intesis credentials are empty!")
    sys.exit(1)

controller = None
loop = None
command_lock = False

# =========================
# TEMPERATURE HELPERS
# =========================
def c_to_f(celsius):
    """Convert Celsius to Fahrenheit, rounded to nearest integer."""
    return round(celsius * 9 / 5 + 32)

def f_to_c(fahrenheit):
    """Convert Fahrenheit to Celsius, rounded to nearest integer (Intesis only accepts °C)."""
    return round((fahrenheit - 32) * 5 / 9)

def to_display_temp(celsius_value):
    """Convert a Celsius value from Intesis to the configured display unit."""
    if celsius_value is None:
        return None
    val = float(celsius_value)
    return c_to_f(val) if TEMP_UNIT == "F" else round(val)

def to_intesis_temp(display_value):
    """Convert a display-unit value from MQTT to Celsius for Intesis."""
    val = int(round(float(display_value)))
    return f_to_c(val) if TEMP_UNIT == "F" else val

# =========================
# MQTT CLIENT
# =========================
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
if MQTT_USER and MQTT_PASS:
    client.username_pw_set(MQTT_USER, MQTT_PASS)

# =========================
# INTESIS ACTIONS
# =========================
async def handle_command(device_id, command, payload):
    global command_lock
    try:
        val = payload.strip().lower()
        base = f"intesis/{device_id}/state"
        command_lock = True

        if command == "power":
            client.publish(f"{base}/power", val.upper(), retain=True)
            client.publish(f"{base}/mode", "off" if val == "off" else "auto", retain=True)
        elif command == "mode":
            client.publish(f"{base}/mode", val, retain=True)
            if val != "off":
                client.publish(f"{base}/power", "ON", retain=True)
        elif command == "temperature":
            # Publish back in display unit (what HA sent us)
            display_temp = int(round(float(payload)))
            client.publish(f"{base}/temperature", str(display_temp), retain=True)
        elif command == "fan":
            client.publish(f"{base}/fan", val, retain=True)

        if command == "power":
            if val == "on":
                await controller.set_power_on(device_id)
            else:
                await controller.set_power_off(device_id)
        elif command == "mode":
            if val == "off":
                await controller.set_power_off(device_id)
            else:
                print(f"🔌 Sending initial Power ON trigger to {device_id}...")
                await controller.set_power_on(device_id)
                await asyncio.sleep(1.5)

                print(f"❄ Directing mode alteration frame -> Mode: {val}")
                if val == "cool":
                    await controller.set_mode_cool(device_id)
                elif val == "dry":
                    await controller.set_mode_dry(device_id)
                elif val == "fan_only":
                    await controller.set_mode_fan(device_id)
                elif val == "auto":
                    await controller.set_mode_auto(device_id)

        elif command == "temperature":
            # Always send Celsius to Intesis regardless of display unit
            intesis_temp = to_intesis_temp(payload)
            print(f"🌡 Temperature command: {payload}°{TEMP_UNIT} → {intesis_temp}°C sent to Intesis")
            await controller.set_temperature(device_id, intesis_temp)
        elif command == "fan":
            await controller.set_fan_speed(device_id, val)

        print(f"✔ Command chain execution complete: {device_id} {command} -> {payload}")
        await asyncio.sleep(2.5)
        await publish_state(device_id)

    except Exception as e:
        print(f"❌ Command execution error on {device_id} ({command}):", e)
    finally:
        command_lock = False

# =========================
# MQTT CALLBACKS
# =========================
def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✔ Connected to MQTT Broker successfully!")
        client.subscribe("intesis/+/set/#")
    else:
        print(f"❌ MQTT Connection failed with code {reason_code}")

def on_message(client, userdata, msg):
    global loop
    topic = msg.topic
    payload = msg.payload.decode()
    print(f"📩 Incoming MQTT: {topic} -> {payload}")
    parts = topic.split("/")
    if len(parts) < 4:
        return
    device_id = parts[1]
    command = parts[3]
    asyncio.run_coroutine_threadsafe(handle_command(device_id, command, payload), loop)

# =========================
# PUBLISH FUNCTIONS
# =========================
async def publish_state(device_id):
    try:
        power = controller.get_power_state(device_id)
        mode = controller.get_mode(device_id)
        setpoint = controller.get_setpoint(device_id)   # always °C from Intesis
        ambient = controller.get_temperature(device_id) # always °C from Intesis
        fan = controller.get_fan_speed(device_id)

        base = f"intesis/{device_id}/state"
        is_on = power in [True, "on", "ON"]

        client.publish(f"{base}/power", "ON" if is_on else "OFF", retain=True)
        ha_mode = str(mode).lower() if is_on else "off"
        if ha_mode == "fan":
            ha_mode = "fan_only"

        client.publish(f"{base}/mode", ha_mode, retain=True)

        if setpoint is not None:
            display_setpoint = to_display_temp(setpoint)
            client.publish(f"{base}/temperature", str(display_setpoint), retain=True)

        if ambient is not None:
            display_ambient = to_display_temp(ambient)
            client.publish(f"{base}/current_temperature", str(display_ambient), retain=True)

        if fan:
            client.publish(f"{base}/fan", str(fan).lower(), retain=True)

    except Exception as e:
        print(f"❌ State query error for {device_id}:", e)

async def publish_discovery(device_id, name):
    topic = f"homeassistant/climate/{device_id}/config"
    fan_modes = ["quiet", "low", "medium", "high", "auto"]

    # Temperature range in the configured display unit
    if TEMP_UNIT == "F":
        temp_min = c_to_f(16)   # 61°F
        temp_max = c_to_f(30)   # 86°F
    else:
        temp_min = 16
        temp_max = 30

    payload = {
        "name": name,
        "uniq_id": f"intesis_{device_id}",
        "object_id": f"intesis_{device_id}",
        "temperature_unit": TEMP_UNIT,   # tells HA which unit to display
        "mode_cmd_t": f"intesis/{device_id}/set/mode",
        "mode_stat_t": f"intesis/{device_id}/state/mode",
        "temp_cmd_t": f"intesis/{device_id}/set/temperature",
        "temp_stat_t": f"intesis/{device_id}/state/temperature",
        "curr_temp_t": f"intesis/{device_id}/state/current_temperature",
        "fan_mode_cmd_t": f"intesis/{device_id}/set/fan",
        "fan_mode_stat_t": f"intesis/{device_id}/state/fan",
        "pow_cmd_t": f"intesis/{device_id}/set/power",
        "pow_stat_t": f"intesis/{device_id}/state/power",
        "modes": ["off", "cool", "dry", "fan_only", "auto"],
        "fan_modes": fan_modes,
        "temp_min": temp_min,
        "temp_max": temp_max,
        "temp_step": 1,
        "device": {
            "identifiers": [f"intesis_{device_id}"],
            "name": name,
            "manufacturer": "Intesis",
            "model": "IntesisHome AC Bridge"
        }
    }
    client.publish(topic, json.dumps(payload), retain=True)
    print(f"📡 Sent updated MQTT Discovery configurations for: {name} (unit: °{TEMP_UNIT})")

# =========================
# MAIN
# =========================
async def main():
    global controller, loop, command_lock
    loop = asyncio.get_running_loop()

    print(f"🌡 Temperature display unit: °{TEMP_UNIT}")
    print("🔄 Connecting to IntesisHome Cloud...")
    controller = IntesisHome(INTESIS_USER, INTESIS_PASS)
    await controller.connect()

    devices = controller.get_devices()
    print("🏠 Devices found:", devices)

    client.on_connect = on_connect
    client.on_message = on_message

    print(f"🌐 Connecting to MQTT Broker at {MQTT_HOST}...")
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()

    for device_id in devices:
        name = controller.get_device_name(device_id)
        await publish_discovery(device_id, name)
        await publish_state(device_id)

    print("🚀 Local Add-on Engine Running.")
    while True:
        try:
            if not command_lock:
                for device_id in devices:
                    await publish_state(device_id)
        except Exception as loop_err:
            print("⚠️ Status loop exception:", loop_err)
        await asyncio.sleep(UPDATE_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
