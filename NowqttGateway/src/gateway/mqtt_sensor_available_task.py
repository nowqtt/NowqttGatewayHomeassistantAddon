import logging
import time

from .nowqtt_device_tree import NowqttDevices

def mqtt_sensor_available_task(nowqtt_devices: NowqttDevices, lock):
    while True:
        with lock:
            devices_to_disconnect_mqtt = []

            logging.debug(f"++++Availa Task: {len(nowqtt_devices.devices.keys())} Devices connected: {nowqtt_devices.devices.keys()}")

            for device_mac_address, device in nowqtt_devices.devices.items():
                if device.last_seen_timestamp + device.seconds_until_timeout < int(time.time()):
                    devices_to_disconnect_mqtt.append(device_mac_address)

                    device.hop_count_entity.mqtt_publish_availability("offline")

            # Disconnect selected clients
            for device in devices_to_disconnect_mqtt:
                nowqtt_devices.del_element(device)

        # Run every 10 seconds
        time.sleep(10)
