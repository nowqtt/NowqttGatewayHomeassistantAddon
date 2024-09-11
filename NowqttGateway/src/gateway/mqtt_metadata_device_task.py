import json
import logging
import time
import global_vars

import paho.mqtt.client as mqtt


def get_mqtt_discovery_topic():
    device = {
        "identifiers": "NowQtt",
        "suggested_area": "Mein Zimmer",
        "manufacturer": "NowQtt LLC Inc. \u2122",
        "name": "NowQtt"
    }

    send_reset_button = {
        "availability_topic": "homeassistant/available/NowQtt",
        "command_topic": "homeassistant/button/nowqtt/trigger_reset/com",
        "name": "NowQtt Trigger Reset",
        "unique_id": "nowqtt_trigger_reset",
        "object_id": "nowqtt_trigger_reset",
        "device_class": "restart",
        "device": device
    }
    send_reset_button_discovery_topic = "homeassistant/button/nowqtt/trigger_reset/config"

    return [
        {
            "discovery_message": send_reset_button,
            "discovery_topic": send_reset_button_discovery_topic
        }
    ]


class MqttMetadataDevice:
    def __init__(self):
        self.mqtt_client = mqtt.Client(client_id="nowqtt_management")
        self.mqtt_sensors = get_mqtt_discovery_topic()
    def on_connect(self, client, userdata, flags, rc):
        logging.info("MQTT Management Device connected")

        for sensor in self.mqtt_sensors:
            self.mqtt_client.publish(sensor["discovery_topic"], json.dumps(sensor["discovery_message"]))
            self.mqtt_client.publish(sensor["discovery_message"]["availability_topic"], "online")

            if "command_topic" in sensor["discovery_message"]:
                self.mqtt_client.subscribe(sensor["discovery_message"]["command_topic"])

    def on_message(self, client, userdata, msg):
        if msg.topic == "homeassistant/button/nowqtt/trigger_reset/com":
            if msg.payload.decode("utf-8") == "PRESS":
                logging.info("Send reset message")
                global_vars.serial.write(bytearray.fromhex("FF13ACFE00"))

    def on_disconnect(self, client, userdata, rc):
        logging.info('Mqtt Management Device %s disconnected', client._client_id.decode("utf-8"))

    def connect_to_mqtt(self):
        try:
            self.mqtt_client.connect(global_vars.mqtt_client_credentials["address"],
                                     global_vars.mqtt_client_credentials["port"], 60)
        except ConnectionRefusedError:
            logging.info("Connection refused. Retrying in 10 seconds...")
            time.sleep(10)
            self.connect_to_mqtt()

    def start_mqtt_task(self):
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.on_disconnect = self.on_disconnect

        self.mqtt_client.username_pw_set(global_vars.mqtt_client_credentials["username"],
                                         global_vars.mqtt_client_credentials["password"])

        self.connect_to_mqtt()

        self.mqtt_client.loop_forever()