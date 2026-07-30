import logging
import threading
import time
from typing import Dict

from nowqtt_database import insert_device_activity_table

from .serial_send_helper import command_to_serial


class NowqttDevices:
    def __init__(self, mqtt_gateway):
        self.devices: Dict[str, Device] = {}
        self._mqtt_gateway = mqtt_gateway
        self._lifecycle_locks = [threading.RLock() for _ in range(64)]

    def lifecycle_lock(self, device_mac_address):
        lock_index = int(device_mac_address[-2:], 16) % len(self._lifecycle_locks)
        return self._lifecycle_locks[lock_index]

    def has_device(self, device_mac_address):
        return device_mac_address in self.devices

    def has_device_and_entity(self, device_mac_address, entity_id):
        device = self.devices.get(device_mac_address)
        return device is not None and device.has_entity(entity_id)

    def get_entity(self, device_mac_address, entity_id):
        return self.devices[device_mac_address].entities[entity_id]

    def registration_needs(self, device_mac_address, entity_id):
        device = self.devices.get(device_mac_address)
        return device is None, device is None or not device.has_entity(entity_id)

    def attach_element(self, header, seconds_until_timeout, hop_entity=None, entity=None):
        device_mac = header["device_mac_address"]
        entity_id = header["entity_id"]
        device = self.devices.get(device_mac)
        is_new_device = device is None

        if is_new_device:
            if hop_entity is None:
                raise ValueError("A new device requires a hop-count entity")
            hop_key = "%s:hop" % device_mac
            device = Device(seconds_until_timeout, hop_entity, hop_key)
            self.devices[device_mac] = device

        entity_key = "%s:%d" % (device_mac, entity_id)
        if not device.has_entity(entity_id):
            if entity is None:
                raise ValueError("A new entity requires a prepared MQTT entity")
            device.entities[entity_id] = entity
            device.entity_keys[entity_id] = entity_key
        else:
            entity = device.entities[entity_id]

        device.seconds_until_timeout = seconds_until_timeout
        device.set_last_seen_timestamp_to_now()
        return device, entity, is_new_device

    def prepare_hop_entity(self, device_mac, config_topic, mqtt_config):
        return self._mqtt_gateway.register_entity(
            "%s:hop" % device_mac, config_topic, mqtt_config
        )

    def prepare_entity(self, header, config_topic, mqtt_config):
        device_mac = header["device_mac_address"]
        entity_id = header["entity_id"]
        return self._mqtt_gateway.register_entity(
            "%s:%d" % (device_mac, entity_id),
            config_topic,
            mqtt_config,
            command_to_serial(device_mac, entity_id)
            if mqtt_config.get("command_topic") else None,
        )

    def update_hop_entity(self, device, config_topic, mqtt_config):
        self._mqtt_gateway.update_entity(
            device.hop_count_entity, config_topic, mqtt_config
        )

    def update_entity(self, header, entity, config_topic, mqtt_config):
        handler = (
            command_to_serial(header["device_mac_address"], header["entity_id"])
            if mqtt_config.get("command_topic") else None
        )
        self._mqtt_gateway.update_entity(entity, config_topic, mqtt_config, handler)

    def disconnect_device(self, device_mac_address, device, publish_availability=True):
        removed_any = False
        for entity_key, entity in device.all_entities():
            removed_any = self._mqtt_gateway.unregister_entity(
                entity_key,
                entity,
                publish_availability=publish_availability,
            ) or removed_any
        if removed_any and publish_availability:
            insert_device_activity_table(device_mac_address, 0)
        return removed_any

    def set_last_seen_timestamp_to_now(self, device_mac_address):
        device = self.devices.get(device_mac_address)
        if device is not None:
            device.set_last_seen_timestamp_to_now()

    def snapshot_addresses(self):
        return list(self.devices)

    def pop_timed_out(self, now):
        timed_out = []
        for device_mac_address, device in list(self.devices.items()):
            if device.last_seen_timestamp + device.seconds_until_timeout < now:
                timed_out.append((device_mac_address, self.devices.pop(device_mac_address)))
        return timed_out

class Device:
    def __init__(self, seconds_until_timeout, hop_count_entity, hop_key):
        self.last_seen_timestamp = int(time.time())
        self.seconds_until_timeout = seconds_until_timeout
        self.entities = {}
        self.entity_keys = {}
        self.hop_count_entity = hop_count_entity
        self.hop_key = hop_key

    def has_entity(self, entity_id):
        return entity_id in self.entities

    def set_last_seen_timestamp_to_now(self):
        self.last_seen_timestamp = int(time.time())

    def all_entities(self):
        entities = [(self.hop_key, self.hop_count_entity)]
        entities.extend(
            (self.entity_keys[entity_id], entity)
            for entity_id, entity in self.entities.items()
        )
        return entities


__all__ = ["Device", "NowqttDevices"]
