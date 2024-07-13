import time
from json import JSONDecodeError

import uuid

import global_vars

import json
import logging
import atexit
from datetime import datetime


from threading import Thread

from database import insert_hop_table, insert_trace_table
from . import mqtt_sensor_available_task

from . import trace_route_task

from .formatter import (
    expand_sensor_config,
    format_mqtt_rssi_config_topic,
    expand_header_message)
from .nowqtt_device_tree import NowqttDevices


def process_serial_log_message(message):
    logging.info(message)

    with open("../logfile.txt", "a") as log_file:
        log_file.write(datetime.now().strftime("%H:%M:%S %m.%d.%Y") + "\t" + message + "\n")


def handle_trace_route_message():
    message_length = int.from_bytes(global_vars.serial.read(1), "little")
    if message_length == 0:
        raise TimeoutError("Partner Timeout")

    serial_header = global_vars.serial.read(6)
    logging.debug("Trace Destination: %s", serial_header.hex())

    serial_message = global_vars.serial.read(message_length-6)
    serial_message_string = ''.join('{:02x}'.format(x) for x in serial_message)
    logging.debug("Trace Message: %s", serial_message_string)

    trace_uuid = str(uuid.uuid4())
    insert_trace_table(serial_header.hex(), trace_uuid)

    hop_count = int((message_length-6) / 7)
    for x in range(hop_count):
        hop_mac_address = serial_message_string[x*14:(x*14)+12]
        hop_rssi_raw = serial_message_string[(x*14)+12:(x*14)+14]
        hop_rssi = int(hop_rssi_raw, 16) - 256

        insert_hop_table(trace_uuid, x, hop_mac_address, hop_rssi)


class SerialTask:
    def __init__(self):
        self.nowqtt_devices = NowqttDevices()

        self.config_message_request_cooldown = {}

    def request_config_message(self, header):
        self.config_message_request_cooldown[header["device_mac_address"]] = time.time()

        message = ("FF13AB0100" +
                   header["device_mac_address"] +
                   "{:02d}".format(global_vars.SerialCommands.RESET.value) +
                   "00")

        reset_message = bytearray.fromhex(message)
        reset_message[4] = len(reset_message) - 5

        global_vars.serial.write(reset_message)

        logging.debug("request config on unknown state message. Header: %s\n", header["device_mac_address"])

    def process_mqtt_state_message(self, message, header):
        if self.nowqtt_devices.has_device_and_entity(header["device_mac_address"], header["entity_id"]):
            entity = self.nowqtt_devices.get_entity(header["device_mac_address"], header["entity_id"])
            entity.mqtt_publish(message)
        else:
            # Test if cooldown exists
            if header["device_mac_address"] in self.config_message_request_cooldown:
                # Test if cooldown is longer then five seconds ago
                if time.time() - self.config_message_request_cooldown[header["device_mac_address"]] >= global_vars.config["cooldown_between_config_request_on_unknown_sensor"]:
                    self.request_config_message(header)
            else:
                self.request_config_message(header)

    def process_mqtt_config_message(self, message, header):
        mqtt_topic = "homeassistant" + message.split("|")[0][1:]
        mqtt_message = message.split("|")[1]
        mqtt_client_name = mqtt_topic.split("/")[3]

        try:
            mqtt_config, seconds_until_timeout = expand_sensor_config(
                json.loads(mqtt_message),
                mqtt_client_name,
                mqtt_topic,
                header
            )

            if not self.nowqtt_devices.has_device_and_entity(header["device_mac_address"], header["entity_id"]):
                mqtt_subscriptions = ["homeassistant/status"]

                # If there is a command topic append it to the subscriptions
                if global_vars.platforms[mqtt_topic.split("/")[1]]['command']:
                    mqtt_subscriptions.append(mqtt_config["command_topic"])

                # Prepare RSSI MQTT
                mqtt_config_topic_rssi, mqtt_config_message_rssi = format_mqtt_rssi_config_topic(
                    message,
                    mqtt_config['availability_topic'],
                    header
                )

                self.nowqtt_devices.add_element(header,
                                                mqtt_config,
                                                mqtt_subscriptions,
                                                mqtt_topic + "onfig",
                                                mqtt_config_message_rssi,
                                                mqtt_config_topic_rssi,
                                                seconds_until_timeout)
        except JSONDecodeError:
            logging.debug('JSON decoder Error')

    def process_heartbeat(self, header, message):
        if self.nowqtt_devices.has_device(header["device_mac_address"]):
            self.nowqtt_devices.devices[header["device_mac_address"]].rssi_entity.mqtt_publish(message)
        else:
            self.request_config_message(header)

    def process_serial_message(self, message, header):
        # Set last seen message
        self.nowqtt_devices.set_last_seen_timestamp_to_now(header["device_mac_address"])

        # ESP has started. Disconnect and clear MQTT connections
        if header["command_type"] == global_vars.SerialCommands.RESET.value:
            self.nowqtt_devices.mqtt_disconnect_all()
            self.nowqtt_devices = NowqttDevices()
        # MQTT state message
        elif header["command_type"] == global_vars.SerialCommands.STATE.value:
            self.process_mqtt_state_message(message, header)
        # MQTT config message
        elif header["command_type"] == global_vars.SerialCommands.CONFIG.value:
            self.process_mqtt_config_message(message, header)
        # log message
        elif header["command_type"] == global_vars.SerialCommands.LOG.value:
            process_serial_log_message(message)
        # heartbeat
        elif header["command_type"] == global_vars.SerialCommands.HEARTBEAT.value:
            self.process_heartbeat(header, 10)

    def disconnect_all_mqtt_clients(self):
        self.nowqtt_devices.mqtt_disconnect_all()
        logging.debug("Program exits. Disconnecting all mqtt clients")

    # Receive serial messages
    def start_serial_task(self):
        # Cleanup function when program exits
        atexit.register(self.disconnect_all_mqtt_clients)

        # Test if sensor is available
        t = Thread(target=mqtt_sensor_available_task.MQTTSensorAvailableTask(
            self.nowqtt_devices
        ).run())
        t.daemon = True
        t.start()

        # Trace route
        t = Thread(target=trace_route_task.TraceRouteTask(
            self.nowqtt_devices
        ).run())
        t.daemon = True
        t.start()

        # clear the serial input buffer
        global_vars.serial.reset_input_buffer()

        logging.info("RUNNING")

        send_header = bytearray.fromhex("FF13AB")
        while True:
            counter = 0
            while counter < 3:
                serial_begin_message = global_vars.serial.read(1)

                if len(serial_begin_message) == 0:
                    raise TimeoutError("Partner Timeout")
                if serial_begin_message == send_header[counter:counter + 1]:
                    counter += 1
                else:
                    counter = 0

            service_byte = global_vars.serial.read(1)
            if service_byte.hex() == "ff":
                handle_trace_route_message()
            else:
                message_length = int.from_bytes(global_vars.serial.read(1), "little")
                if message_length == 0:
                    raise TimeoutError("Partner Timeout")

                serial_header = global_vars.serial.read(8)
                logging.debug("Header: %s", serial_header.hex())

                serial_message = global_vars.serial.read(message_length-8).decode("utf-8", errors='ignore').strip()
                logging.debug("Message: %s", serial_message)

                header = expand_header_message(serial_header)
                self.process_serial_message(serial_message, header)
