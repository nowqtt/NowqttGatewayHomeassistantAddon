import logging
import threading
import time

from nowqtt_device_tree import NowqttDevices
import global_vars

class TraceRouteTask:
    def __init__(self, nowqtt_devices):
        self.nowqtt_devices: NowqttDevices = nowqtt_devices

    def run(self):
        for device_mac_address, device in self.nowqtt_devices.devices.items():
            formatted_message = bytearray.fromhex("FF13AD06")
            formatted_message.extend(bytearray.fromhex(device_mac_address))

            global_vars.serial.write(formatted_message)

            logging.debug('Trace Request %s', str(formatted_message))

            time.sleep(1)

        t = threading.Timer(30.0, self.run)
        t.daemon = True
        t.start()


