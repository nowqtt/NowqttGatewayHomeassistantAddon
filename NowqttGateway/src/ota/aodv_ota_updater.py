import logging
import math
import time
from enum import Enum
from threading import Thread

import global_vars
from gateway import send_ota_init_serial_message, send_ota_data_serial_message


class OtaCommands(Enum):
    OTA_INIT = 101
    OTA_READY = 102
    OTA_DATA = 103
    OTA_RETRANSMIT = 104
    OTA_DISCOVER = 105
    OTA_DISCOVER_RESPONSE = 106

class OtaManager:
    def __init__(self, ota_data_file, mac_address):
        self.ota_data_file = ota_data_file
        self.mac_address = mac_address

        self.payload_size = 232

        self.packets_to_retransmit = []
        self.already_sending = False
        self.last_retransmit_time = None

    def handle_serial_message(self, serial_message):
        if not self.already_sending:
            if serial_message[0] == OtaCommands.OTA_READY.value:
                t = Thread(target=self.send_init_ota_data)
                t.daemon = True
                t.start()

            elif serial_message[0] == OtaCommands.OTA_RETRANSMIT.value:
                self.packets_to_retransmit.append(int.from_bytes(serial_message[1:4], "little"))
                self.last_retransmit_time = time.time()

    def init_ota(self):
        packet_count = math.ceil(len(self.ota_data_file) / self.payload_size)

        logging.info("OTA update %s: Binary %i bytes --> %i Packets", self.mac_address, len(self.ota_data_file), packet_count)

        send_ota_init_serial_message(
            "00",
            self.mac_address,
            OtaCommands.OTA_INIT.value,
            len(self.ota_data_file),
        )

        t = Thread(target=self.retransmit_listener)
        t.daemon = True
        t.start()

    def send_init_ota_data(self):
        self.already_sending = True
        logging.info("Got Init -> sending data")
        for i in range((len(self.ota_data_file) // self.payload_size) + 1):
            if i % 100 == 0:
                logging.info('Sending package %d', i)
            self.send_payload_packet(i)

        self.already_sending = False

    def retransmit_listener(self):
        while True:
            if self.last_retransmit_time is not None:
                if time.time() - self.last_retransmit_time > 1.5:
                    self.retransmit_ota_data()
                    break
            time.sleep(0.1)  # Check every 100ms for efficiency

    def retransmit_ota_data(self):
        self.already_sending = True

        if not self.packets_to_retransmit:
            logging.info("OTA %s: No more packages to retransmit", self.mac_address)

            global_vars.ota_queue.pop(self.mac_address)
            return

        logging.info("Retransmitting %d packages", len(self.packets_to_retransmit))

        for retransmit in self.packets_to_retransmit:
            self.send_payload_packet(retransmit)

        self.packets_to_retransmit = []
        self.already_sending = False
        self.last_retransmit_time = None

        t = Thread(target=self.retransmit_listener)
        t.daemon = True
        t.start()

    def send_payload_packet(self, num):
        if num == (len(self.ota_data_file) // self.payload_size):
            payload = self.ota_data_file[num * self.payload_size:]
        else:
            payload = self.ota_data_file[num * self.payload_size:(num + 1) * self.payload_size]

        send_ota_data_serial_message(
            "00",
            self.mac_address,
            OtaCommands.OTA_DATA.value,
            num,
            payload
        )

        time.sleep(0.05)
