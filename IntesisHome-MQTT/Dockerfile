# 1. Base Image - Multi-architecture manifest handled natively by BuildKit
FROM ghcr.io/home-assistant/base:latest

# 2. Environment Variables - Force Python to print logs instantly to Home Assistant
ENV PYTHONUNBUFFERED=1

# 3. System Dependencies - Install Python 3 and package manager
RUN apk add --no-cache \
    python3 \
    py3-pip

# 4. Python Libraries - Install MQTT and Intesis packages globally
RUN pip3 install --no-cache-dir \
    paho-mqtt \
    pyintesishome \
    --break-system-packages

# 5. File Management - Move scripts to safe paths
COPY intesis_mqtt.py /intesis_mqtt.py

# 6. Service Initiation - Move execution wrapper into s6-overlay management folder
COPY run.sh /etc/services.d/intesis_mqtt/run

# 7. Permissions - Ensure file paths possess structural execution bits
RUN chmod a+x /etc/services.d/intesis_mqtt/run
