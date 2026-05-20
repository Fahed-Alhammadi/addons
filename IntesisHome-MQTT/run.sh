#!/usr/bin/with-contenv bashio

export INTESIS_USER=$(bashio::config 'intesis_user')
export INTESIS_PASS=$(bashio::config 'intesis_pass')
export MQTT_HOST=$(bashio::config 'mqtt_host')
export MQTT_PORT=$(bashio::config 'mqtt_port')
export MQTT_USER=$(bashio::config 'mqtt_user')
export MQTT_PASS=$(bashio::config 'mqtt_pass')
export UPDATE_INTERVAL=$(bashio::config 'update_interval')

echo "🚀 Starting Intesis MQTT Gateway Python application..."
python3 /intesis_mqtt.py