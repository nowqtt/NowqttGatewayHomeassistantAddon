import json
import logging
from typing import Dict
import time

import paho.mqtt.client as mqtt
from threading import Thread

from nowqtt_database import insert_device_activity_table
from .mqtt_task import MQTTTask


def create_mqtt_client(header, mqtt_config, client_id, mqtt_config_topic, mqtt_subscriptions):
    new_client = mqtt.Client(client_id=client_id)

    t = Thread(target=MQTTTask(
        new_client,
        mqtt_subscriptions,
        header["device_mac_address"],
        header["entity_id"],
        mqtt_config,
        mqtt_config_topic
    ).start_mqtt_task)
    t.daemon = True
    t.start()

    while not new_client.is_connected():
        time.sleep(0.1)

    return Entity(
        mqtt_config["state_topic"],
        new_client,
        mqtt_config['availability_topic'],
        mqtt_config_topic
    )


class NowqttDevices:
    def __init__(self):
        self.devices: Dict[bytearray, Device] = {}

    def has_device(self, device_mac_address):
        for device in self.devices.keys():
            if device == device_mac_address:
                return True
        return False

    def has_device_and_entity(self, device_mac_address, entity_id):
        if self.has_device(device_mac_address):
            return self.devices[device_mac_address].has_entity(entity_id)
        else:
            return False

    def get_entity(self, device_mac_address, entity_id):
        return self.devices[device_mac_address].entities[entity_id]

    def add_element(self,
                    header,
                    mqtt_config,
                    mqtt_subscriptions,
                    mqtt_config_topic,
                    mqtt_config_message_hop_count,
                    mqtt_config_topic_hop_count,
                    seconds_until_timeout):
        # Test if device exists
        if self.has_device(header["device_mac_address"]):
            device = self.devices[header["device_mac_address"]]
        else:
            new_hop_count_entity = create_mqtt_client(
                header,
                mqtt_config_message_hop_count,
                header["device_mac_address"] + "00",
                mqtt_config_topic_hop_count,
                ["homeassistant/status"]
            )

            device = Device(seconds_until_timeout, new_hop_count_entity)
            device.entities[0] = new_hop_count_entity

            device.hop_count_entity.mqtt_publish_availability("online")

            insert_device_activity_table(header["device_mac_address"], 1)

        # Test if entity exists
        if not device.has_entity(header["entity_id"]):
            entity = create_mqtt_client(
                header,
                mqtt_config,
                header["device_mac_address_and_entity_id"],
                mqtt_config_topic,
                mqtt_subscriptions
            )

            device.entities[header["entity_id"]] = entity

        device.set_last_seen_timestamp_to_now()

        self.devices[header["device_mac_address"]] = device

    def del_element(self, device_mac_address):
        if self.has_device(device_mac_address):
            insert_device_activity_table(device_mac_address, 0)
            self.devices[device_mac_address].mqtt_disconnect_all()

            del self.devices[device_mac_address]

    def set_last_seen_timestamp_to_now(self, device_mac_address):
        if self.has_device(device_mac_address):
            self.devices[device_mac_address].set_last_seen_timestamp_to_now()

    def mqtt_disconnect_all(self):
        logging.info("Disconnecting all devices")

        for device in self.devices.values():
            device.mqtt_disconnect_all()

        for mac_address in self.devices.keys():
            insert_device_activity_table(mac_address, 0)

    def set_activity_to_offline(self):
        for mac_address in self.devices.keys():
            insert_device_activity_table(mac_address, 0)

class Device:
    def __init__(self, seconds_until_timeout, hop_count_entity):
        self.last_seen_timestamp = 0
        self.seconds_until_timeout = seconds_until_timeout

        self.entities: Dict[int, Entity] = {}
        self.hop_count_entity: Entity = hop_count_entity

    def has_entity(self, entity_id):
        return entity_id in self.entities

    def set_last_seen_timestamp_to_now(self):
        self.last_seen_timestamp = int(time.time())

    def mqtt_disconnect_all(self):
        for device in self.entities.values():
            device.mqtt_disconnect()

class Entity:
    def __init__(self, mqtt_state_topic, mqtt_client, mqtt_availability_topic, mqtt_config_topic):
        self.mqtt_state_topic = mqtt_state_topic
        self.mqtt_client = mqtt_client
        self.mqtt_availability_topic = mqtt_availability_topic
        self.mqtt_config_topic = mqtt_config_topic

    def mqtt_publish(self, message):
        self.mqtt_client.publish(self.mqtt_state_topic, message)
        self.mqtt_client.set_last_known_state(message)

    def mqtt_publish_config_message(self, mqtt_config_message):
        self.mqtt_client.publish(self.mqtt_config_topic, json.dumps(mqtt_config_message))

    def mqtt_publish_availability(self, state):
        self.mqtt_client.publish(self.mqtt_availability_topic, state, qos=1, retain=True)

    def mqtt_disconnect(self):
        logging.debug("Disconnecting %s", self.mqtt_client._client_id.decode("utf-8"))

        self.mqtt_publish_availability("offline")
        self.mqtt_client.disconnect()
