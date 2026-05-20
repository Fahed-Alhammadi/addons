ARG BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest
FROM $BUILD_FROM

# Install Python and pip
RUN apk add --no-cache python3 py3-pip

# Install necessary libraries
RUN pip3 install --no-cache-dir paho-mqtt pyintesishome --break-system-packages

# Copy local data paths
COPY run.sh /
COPY intesis_mqtt.py /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
