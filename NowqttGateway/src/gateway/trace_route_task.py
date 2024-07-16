import copy
import logging
import threading
import time

from .nowqtt_device_tree import NowqttDevices

from .serial_send_helper import send_serial_message


class TraceRouteTask:
    def __init__(self, nowqtt_devices):
        self.nowqtt_devices: NowqttDevices = nowqtt_devices

    def run(self):
        mac_address_list = []
        for device_mac_address, device in self.nowqtt_devices.devices.items():
            mac_address_list.append(copy.copy(device_mac_address))

        for device_mac_address in mac_address_list:
            send_serial_message("FF", device_mac_address, None, None, None)

            logging.debug('Trace Request %s', device_mac_address)

            time.sleep(1)

        t = threading.Timer(30.0, self.run)
        t.daemon = True
        t.start()
