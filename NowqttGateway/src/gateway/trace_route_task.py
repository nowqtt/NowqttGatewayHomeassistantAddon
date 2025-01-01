import copy
import logging
import time

from .nowqtt_device_tree import NowqttDevices
from .serial_send_helper import send_serial_message

def trace_route_task(nowqtt_devices: NowqttDevices, lock):
    while True:
        mac_address_list = []
        with lock:
            for device_mac_address, device in nowqtt_devices.devices.items():
                mac_address_list.append(copy.copy(device_mac_address))

        for device_mac_address in mac_address_list:
            send_serial_message("FF", device_mac_address, None, None, None)

            logging.debug('Trace Request %s', device_mac_address)

            time.sleep(1)

        # Run every 30 seconds
        time.sleep(30)