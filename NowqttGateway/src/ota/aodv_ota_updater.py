import logging
import time
from ctypes import *
from enum import Enum
from threading import Thread

import global_vars
from gateway import send_ota_init_serial_message


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

        self.qos_sendheader = bytearray.fromhex("FF13AB0006")
        self.sendheader = bytearray.fromhex("FF13AC0006")

        self.preamble_len = len(self.sendheader)
        self.payload_size = 232
        self.sendheader.extend(bytearray.fromhex(self.mac_address))
        self.qos_sendheader.extend(bytearray.fromhex(self.mac_address))

        self.ota_data_len = len(self.ota_data_file)

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

                logging.info("OTA %i", int.from_bytes(serial_message[1:4], "little"))

    def init_ota(self):
        packet_count = self.ota_data_len // self.payload_size

        if (self.ota_data_len % self.payload_size) != 0:
            packet_count += 1
        logging.info("OTA update %s: Binary %i bytes --> %i Packets", self.mac_address, len(self.ota_data_file), packet_count)

        request_msg = bytearray(self.preamble_len)
        request_msg[:] = self.qos_sendheader
        request_msg.append(OtaCommands.OTA_INIT.value)
        request_msg.extend(bytearray(c_uint32(len(self.ota_data_file))))

        logging.info(c_uint32(len(self.ota_data_file)))

        request_msg[self.preamble_len - 1] = len(request_msg) - self.preamble_len
        # global_vars.serial.write(request_msg)

        logging.info("innit message %s", request_msg.hex())

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
        for i in range((self.ota_data_len // self.payload_size) + 1):
            if i % 100 == 0:
                logging.info('Sending package %d', i)
            self.send_payload_packet(i)

        self.already_sending = False

    def retransmit_listener(self):
        logging.info("retransmit_listener starting")
        while True:
            if self.last_retransmit_time is not None:
                if time.time() - self.last_retransmit_time > 1.5:
                    logging.info("2 seconds of inactivity, calling trigger_function")
                    self.retransmit_ota_data()
                    break
            time.sleep(0.1)  # Check every 100ms for efficiency

        logging.info("retransmit_listener ending")

    def retransmit_ota_data(self):
        self.already_sending = True
        logging.info("Retransmitting %d packages", len(self.packets_to_retransmit))

        if not self.packets_to_retransmit:
            global_vars.ota_queue.pop(self.mac_address)
            return

        i = 0
        for retransmit in self.packets_to_retransmit:
            if i % 100 == 0:
                logging.info('Sending package %d', i)
            i+=1

            self.send_payload_packet(retransmit)

        self.packets_to_retransmit = []
        self.already_sending = False
        self.last_retransmit_time = None

        t = Thread(target=self.retransmit_listener)
        t.daemon = True
        t.start()

    def send_payload_packet(self, num):
        send = bytearray(len(self.sendheader))
        send[:] = self.sendheader  # deepcopy
        send.append(OtaCommands.OTA_DATA.value)
        send.extend(bytearray(c_uint32(num)))

        if num == (self.ota_data_len // self.payload_size):
            send.extend(self.ota_data_file[num * self.payload_size:])
        else:
            send.extend(self.ota_data_file[num * self.payload_size:(num + 1) * self.payload_size])

        send[self.preamble_len - 1] = len(send) - self.preamble_len
        global_vars.serial.write(send)
        time.sleep(0.03)
