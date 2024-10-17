import logging
import time
from ctypes import *
from enum import Enum
from threading import Thread

import global_vars


class OtaCommands(Enum):
    OTA_INIT = 101
    OTA_READY = 102
    OTA_DATA = 103
    OTA_RETRANSMIT = 104
    OTA_DISCOVER = 105
    OTA_DISCOVER_RESPONSE = 106


# def read_msg(qos_sendheader):
#     counter = 0
#     while counter < 4:
#         readback = global_vars.serial.read(1)
#
#         if len(readback) == 0:
#             raise TimeoutError("Partner Timeout")
#         if readback == qos_sendheader[counter:counter + 1]:
#             counter += 1
#         else:
#             counter = 0
#
#     read_len = int.from_bytes(global_vars.serial.read(1), "little")
#     if read_len == 0:
#         raise TimeoutError("Partner Timeout")
#
#     data = global_vars.serial.read(read_len)
#     if len(data) != read_len:
#         raise FormatError("Msg encoding Error!")
#
#     return data


class OtaManager:
    def __init__(self, ota_data_file, mac_address):
        self.state = "START"
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

    def handle_serial_message(self, serial_message):
        if serial_message[0] == OtaCommands.OTA_READY.value:
            t = Thread(target=self.send_init_ota_data)
            t.daemon = True
            t.start()

        elif serial_message[0] == OtaCommands.OTA_RETRANSMIT.value:
            self.packets_to_retransmit.append(int.from_bytes(serial_message[1:4], "little"))

    def init_ota(self):
        packet_count = self.ota_data_len // self.payload_size

        if (self.ota_data_len % self.payload_size) != 0:
            packet_count += 1
        logging.info("Read %i bytes from binery --> %i Packets", len(self.ota_data_file), packet_count)

        request_msg = bytearray(self.preamble_len)
        request_msg[:] = self.qos_sendheader
        request_msg.append(OtaCommands.OTA_INIT.value)
        request_msg.extend(bytearray(c_uint32(len(self.ota_data_file))))

        request_msg[self.preamble_len - 1] = len(request_msg) - self.preamble_len
        global_vars.serial.write(request_msg)
        logging.info("message sent")
        # global_vars.serial.flushInput()

    def send_init_ota_data(self):
        logging.info("Got Init -> sending data")
        for i in range((self.ota_data_len // self.payload_size) + 1):
            if i == 0:
                logging.info('send first message')
            if i % 100 == 0:
                logging.info('Hier %d', i)
            self.send_payload_packet(i)

        t = Thread(target=self.retransmit_ota_data)
        t.daemon = True
        t.start()

    def retransmit_ota_data(self):
        logging.info("In retransmit ota")
        time.sleep(2)

        logging.info("In retransmit after wait")

        if not self.packets_to_retransmit:
            global_vars.ota_queue.pop(self.mac_address)
            return

        for retransmit in self.packets_to_retransmit:
            self.send_payload_packet(retransmit)

        self.packets_to_retransmit = []

        t = Thread(target=self.retransmit_ota_data)
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
        # logging.debug("Len in header: %i real len %i", send[preamble_len - 1], len(send))
        global_vars.serial.write(send)
        time.sleep(0.05)

    # def update(self):
    #     # logging.debug("len of %i", len(request_msg))
    #     # logging.debug("Sendheader: %s", request_msg.hex())
    #
    #     # response_msg = read_msg(self.qos_sendheader)
    #     # if response_msg[6] != OtaCommands.OTA_READY.value:
    #     #     raise NameError("Wrong Response after init")
    #
    #     # logging.info("Got Init")
    #     # bar = IncrementalBar('Transmitting', max=(self.ota_data_len // self.payload_size) + 1)
    #     # for i in range(0, (self.ota_data_len // self.payload_size) + 1):
    #     #     self.send_payload_packet(i)
    #     #     bar.next()
    #     # bar.finish()
    #     # global_vars.serial.timeout = 1
    #
    #     while True:
    #         time.sleep(2)  # wait one esp timeout period to get packets to retransmitt to wait for esp
    #         packets_to_send = []
    #         spinner = Spinner('Getting Retransmissions')
    #         while True:
    #             try:
    #                 packets_to_send.append(int.from_bytes(read_msg(self.qos_sendheader)[7:10], "little"))
    #                 spinner.next()
    #             except TimeoutError:
    #                 # logging.info("Readtimeout --> no more retransmits sending received ones")
    #                 break
    #         spinner.finish()
    #         if len(packets_to_send) == 0: break
    #         bar = IncrementalBar('Retransmitting', max=len(packets_to_send))
    #         for nums in packets_to_send:
    #             self.send_payload_packet(nums)
    #             bar.next()
    #         bar.finish()
    #
    #     logging.info("Done!")

