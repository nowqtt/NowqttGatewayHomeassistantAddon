import logging
import threading
import time

from database import insert_device_activity_table
from .nowqtt_device_tree import NowqttDevices


class MQTTSensorAvailableTask:
    def __init__(self, nowqtt_devices):
        self.nowqtt_devices: NowqttDevices = nowqtt_devices

    def run(self):
        t = threading.Timer(10.0, self.run)
        t.daemon = True
        t.start()

        devices_to_disconnect_mqtt = []

        # for device_mac_address, device in self.nowqtt_devices.devices.items():
        #     for entity in device.entities.values():
        #         logging.debug(entity.mqtt_client._client_id.decode("utf-8"))

        for device_mac_address, device in self.nowqtt_devices.devices.items():
            if device.last_seen_timestamp + device.seconds_until_timeout < int(time.time()):
                devices_to_disconnect_mqtt.append(device_mac_address)

                device.hop_count_entity.mqtt_publish_availability("offline")

                insert_device_activity_table(device_mac_address, 0)

        # Disconnect selected clients
        for device in devices_to_disconnect_mqtt:
            self.nowqtt_devices.devices[device].mqtt_disconnect_all()
            del self.nowqtt_devices.devices[device]
