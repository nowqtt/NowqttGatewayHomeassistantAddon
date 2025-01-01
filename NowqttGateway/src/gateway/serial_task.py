import threading
import time
import uuid
import json
import logging
import atexit
from datetime import datetime

import global_vars

from nowqtt_database import (
    insert_hop_table,
    insert_trace_table,
    find_device_names,
    update_devices_names,
    insert_devices_names
)

from .mqtt_metadata_device_task import MqttMetadataDevice
from .mqtt_sensor_available_task import mqtt_sensor_available_task
from .trace_route_task import trace_route_task
from .formatter import (
    expand_sensor_config,
    format_mqtt_hop_count_config_topic,
    expand_header_message)
from .serial_send_helper import send_serial_message
from .nowqtt_device_tree import NowqttDevices

def process_serial_log_message(message):
    logging.info(message)

    with open("../logfile.txt", "a") as log_file:
        log_file.write(datetime.now().strftime("%H:%M:%S %m.%d.%Y") + "\t" + message + "\n")


def get_hex_string_from_array(hex_string, start, length):
    return hex_string[start: start+length]

def write_device_name_to_db(mac_address, device_name):
    rows = find_device_names(mac_address)

    if len(rows) != 0:
        if rows[0][2] == 0:
            update_devices_names(mac_address, device_name, 0)
    else:
        insert_devices_names(mac_address, device_name, 0)


def calculate_hop_count_to_and_from(mac_address, trace_message, byte_chars_per_hop):
    counter = 0
    count_to = -1 #GW is in the trace but not a hop -> start from -1
    count_from = -1 #GW is in the trace but not a hop -> start from -1

    reached_destination = False
    while counter * byte_chars_per_hop < len(trace_message):
        if not reached_destination:
            if trace_message[counter * byte_chars_per_hop: counter * byte_chars_per_hop + 12] != mac_address:
                count_to += 1
            else:
                reached_destination = True
        else:
            count_from += 1

        counter += 1

    return f'{count_to}/{count_from}'


def handle_ota_init_message():
    message_length = int.from_bytes(global_vars.serial.read(1), "little")
    if message_length == 0:
        raise TimeoutError("Partner Timeout")

    mac_address = global_vars.serial.read(6).hex()
    serial_message = global_vars.serial.read(message_length - 6)

    global_vars.ota_queue[mac_address].handle_serial_message(serial_message)


class SerialTask:
    def __init__(self):
        self.nowqtt_devices = NowqttDevices()

        self.config_message_request_cooldown = {}

        self.lock = threading.Lock()

    def handle_trace_route_message(self):
        message_length = int.from_bytes(global_vars.serial.read(1), "little")
        if message_length == 0:
            raise TimeoutError("Partner Timeout")

        serial_header = global_vars.serial.read(6)
        logging.debug("Trace Destination: %s", serial_header.hex())

        serial_message = global_vars.serial.read(message_length - 6)
        trace_message_string = ''.join('{:02x}'.format(x) for x in serial_message)
        logging.debug("Trace Message: %s", trace_message_string)

        trace_uuid = str(uuid.uuid4())
        insert_trace_table(serial_header.hex(), trace_uuid)

        bytes_per_hop = 6 + 1 + 4 + 1 + 1  # 6 Byte mac, 1 Byte rssi, 4 Byte dest sequ, 1 Byte age, 1 Byte hop-count
        byte_chars_per_hop = bytes_per_hop * 2
        hop_count = int((message_length - 6) / bytes_per_hop)
        for x in range(hop_count):
            current_start_byte = x * byte_chars_per_hop
            start_byte_in_current_hop = 0

            hop_mac_address = get_hex_string_from_array(trace_message_string,
                                                        current_start_byte + start_byte_in_current_hop, 12)

            start_byte_in_current_hop += 12

            hop_rssi_raw = get_hex_string_from_array(trace_message_string,
                                                     current_start_byte + start_byte_in_current_hop, 2)
            hop_rssi = int(hop_rssi_raw, 16) - 256

            start_byte_in_current_hop += 2

            hop_dest_seq_raw = get_hex_string_from_array(trace_message_string,
                                                         current_start_byte + start_byte_in_current_hop, 8)
            hop_dest_seq_bytes = bytes.fromhex(hop_dest_seq_raw)
            hop_dest_seq = int.from_bytes(hop_dest_seq_bytes, byteorder='little')

            start_byte_in_current_hop += 8

            route_age_raw = get_hex_string_from_array(trace_message_string,
                                                      current_start_byte + start_byte_in_current_hop, 2)
            route_age = int(route_age_raw, 16)

            start_byte_in_current_hop += 2

            hop_count_message_raw = get_hex_string_from_array(trace_message_string,
                                                              current_start_byte + start_byte_in_current_hop, 2)
            hop_count_message = int(hop_count_message_raw, 16)

            insert_hop_table(trace_uuid, x, hop_mac_address, hop_rssi, hop_dest_seq, route_age, hop_count_message)

        # Publish hop count
        with self.lock:
            if self.nowqtt_devices.has_device(serial_header.hex()):
                self.nowqtt_devices.devices[serial_header.hex()].hop_count_entity.mqtt_publish(calculate_hop_count_to_and_from(
                    serial_header.hex(),
                    trace_message_string,
                    byte_chars_per_hop
                ))

    def request_config_message(self, header):
        self.config_message_request_cooldown[header["device_mac_address"]] = time.time()

        send_serial_message(
            "01",
            header["device_mac_address"],
            global_vars.SerialCommands.RESET.value,
            0,
            None
        )

        logging.debug("request config on unknown state message. Header: %s\n", header["device_mac_address"])

    def process_mqtt_state_message(self, message, header):
        with self.lock:
            if self.nowqtt_devices.has_device_and_entity(header["device_mac_address"], header["entity_id"]):
                self.nowqtt_devices.get_entity(header["device_mac_address"], header["entity_id"]).mqtt_publish(message)
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
        splitted_message = message.split("|")

        if len(splitted_message) < 2:
            logging.error("Error in config message: %s", message)
            return

        mqtt_message = splitted_message[1]
        mqtt_client_name = mqtt_topic.split("/")[3]

        try:
            mqtt_config, seconds_until_timeout = expand_sensor_config(
                json.loads(mqtt_message),
                mqtt_client_name,
                mqtt_topic,
                header
            )

            write_device_name_to_db(header['device_mac_address'], mqtt_config['dev']['name'])

            with self.lock:
                if not self.nowqtt_devices.has_device_and_entity(header["device_mac_address"], header["entity_id"]):
                    mqtt_subscriptions = ["homeassistant/status"]

                    # If there is a command topic append it to the subscriptions
                    if global_vars.platforms[mqtt_topic.split("/")[1]]['command']:
                        mqtt_subscriptions.append(mqtt_config["command_topic"])

                    # Prepare hop count MQTT
                    mqtt_config_topic_hop_count, mqtt_config_message_hop_count = format_mqtt_hop_count_config_topic(
                        message,
                        mqtt_config['availability_topic'],
                        header
                    )

                    self.nowqtt_devices.add_element(header,
                                                    mqtt_config,
                                                    mqtt_subscriptions,
                                                    mqtt_topic + "onfig",
                                                    mqtt_config_message_hop_count,
                                                    mqtt_config_topic_hop_count,
                                                    seconds_until_timeout)

                # Publish potential new config topic
                else:
                    self.nowqtt_devices.devices[header["device_mac_address"]].entities[header["entity_id"]].mqtt_publish_config_message(mqtt_config)
        except json.JSONDecodeError as e:
            logging.error('JSON decoder Error. Config Message %s. Error %s', message, e)
        except Exception as e:
            logging.error('Error in config message decode: %s', e)

    def process_heartbeat(self, header):
        with self.lock:
            if self.nowqtt_devices.has_device(header["device_mac_address"]):
                return
            else:
                self.request_config_message(header)

    def process_serial_message(self, message, header):
        # Set last seen message
        with self.lock:
            self.nowqtt_devices.set_last_seen_timestamp_to_now(header["device_mac_address"])

        # MQTT state message
        if header["command_type"] == global_vars.SerialCommands.STATE.value:
            self.process_mqtt_state_message(message, header)
        # MQTT config message
        elif header["command_type"] == global_vars.SerialCommands.CONFIG.value:
            self.process_mqtt_config_message(message, header)
        # log message
        elif header["command_type"] == global_vars.SerialCommands.LOG.value:
            process_serial_log_message(message)
        # heartbeat
        elif header["command_type"] == global_vars.SerialCommands.HEARTBEAT.value:
            self.process_heartbeat(header)

    def disconnect_all_mqtt_clients(self):
        with self.lock:
            self.nowqtt_devices.mqtt_disconnect_all()

    # Receive serial messages
    def start_serial_task(self):
        # Cleanup function when program exits
        atexit.register(self.disconnect_all_mqtt_clients)

        # Test if sensor is available
        available_thread = threading.Thread(
            target=mqtt_sensor_available_task,
            args=(self.nowqtt_devices, self.lock),
            daemon=True)
        available_thread.start()

        # Trace route
        trace_route_thread = threading.Thread(
            target=trace_route_task,
            args=(self.nowqtt_devices, self.lock),
            daemon=True)
        trace_route_thread.start()

        # Mqtt metadata and control task
        metadata_thread = threading.Thread(
            target=MqttMetadataDevice().start_mqtt_task,
            daemon = True)
        metadata_thread.start()

        # clear the serial input buffer
        global_vars.serial.reset_input_buffer()

        logging.info("SERIAL TASK RUNNING")

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
                self.handle_trace_route_message()
            elif service_byte.hex() == "00":
                handle_ota_init_message()
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
