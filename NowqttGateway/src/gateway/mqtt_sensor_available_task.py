import logging
import time

from .nowqtt_device_tree import NowqttDevices

def mqtt_sensor_available_task(nowqtt_devices: NowqttDevices, lock, stop_event):
    while not stop_event.is_set():
        with lock:
            logging.debug(
                "Availability task: %d connected devices", len(nowqtt_devices.devices)
            )
            devices_to_disconnect = nowqtt_devices.pop_timed_out(int(time.time()))

        for mac_address, device in devices_to_disconnect:
            with nowqtt_devices.lifecycle_lock(mac_address):
                with lock:
                    replacement_exists = nowqtt_devices.has_device(mac_address)
                nowqtt_devices.disconnect_device(
                    mac_address,
                    device,
                    publish_availability=not replacement_exists,
                )

        stop_event.wait(10)
