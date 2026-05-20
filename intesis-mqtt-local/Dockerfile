FROM ghcr.io/home-assistant/base:latest

# Install Python and pip
RUN apk add --no-cache python3 py3-pip

# Install necessary libraries
RUN pip3 install --no-cache-dir paho-mqtt pyintesishome --break-system-packages

# Copy scripts to their proper locations
COPY intesis_mqtt.py /intesis_mqtt.py

# Put run.sh where s6-overlay expects services to live
COPY run.sh /etc/services.d/intesis_mqtt/run

# Make sure both scripts have execution permissions
RUN chmod a+x /etc/services.d/intesis_mqtt/run

# Copy local data paths
COPY run.sh /
COPY intesis_mqtt.py /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
