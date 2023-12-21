import time
from json import JSONDecodeError

import global_vars

import json
import logging
import atexit
from datetime import datetime

from influxdb_client import Point

from threading import Thread

import mqtt_sensor_available_task
from nowqtt_device_tree import NowqttDevices


def expand_device_config(device):
    device['identifiers'] = "ESP32 " + device.pop('i')
    device['suggested_area'] = device.pop('s')
    device['manufacturer'] = "Ich"
    device['model'] = "ESP32"
    device['name'] = device.pop('n')

    # Set timeout to 60 seconds if not applied
    if 't' in device:
        device['seconds_until_timeout'] = device.pop('t')
    else:
        device['seconds_until_timeout'] = global_vars.config["default_seconds_until_timeout"]

    return device


def expand_sensor_config(mqtt_config, mqtt_client_name, mqtt_topic):
    platform = mqtt_topic.split("/")[1]

    mqtt_config['name'] = mqtt_config.pop('n')
    mqtt_config['unique_id'] = mqtt_client_name
    mqtt_config['object_id'] = mqtt_client_name
    # mqtt_config['availability_topic'] = availability_topic

    if global_vars.platforms[platform]['state']:
        mqtt_config['state_topic'] = mqtt_topic[:len(mqtt_topic) - 1] + "state"
    if global_vars.platforms[platform]['command']:
        mqtt_config['command_topic'] = mqtt_topic + "om"

    # unit_of_measurement only in sensor
    if 'um' in mqtt_config:
        mqtt_config['unit_of_measurement'] = mqtt_config.pop('um')
    # device_class only in sensor
    if 'dc' in mqtt_config:
        mqtt_config['device_class'] = mqtt_config.pop('dc')
    if 'sc' in mqtt_config:
        mqtt_config['state_class'] = mqtt_config.pop('sc')

    # max only in number
    if 'mx' in mqtt_config:
        mqtt_config['max'] = mqtt_config.pop('mx')
    # max only in number
    if 'mn' in mqtt_config:
        mqtt_config['min'] = mqtt_config.pop('mn')
    # max only in number
    if 'st' in mqtt_config:
        mqtt_config['step'] = mqtt_config.pop('st')
    # max only in number
    if 'md' in mqtt_config:
        mqtt_config['mode'] = mqtt_config.pop('md')

    # options only in select
    if 'o' in mqtt_config:
        mqtt_config['options'] = mqtt_config.pop('o')

    mqtt_config['device'] = expand_device_config(mqtt_config.pop('d'))

    mqtt_config['availability_topic'] = "homeassistant/available/" + \
                                        mqtt_config['device']['identifiers'].replace(" ", "_")

    # logging.debug("MQTT Config: %s", mqtt_config)
    return mqtt_config, int(mqtt_config['device'].pop('seconds_until_timeout'))


def expand_header_message(raw_header):
    print(raw_header.hex())
    return {
        "device_mac_address_bytearray": bytearray(raw_header[:6]),
        "device_mac_address_int": int.from_bytes(bytearray(raw_header[:6]), "big"),
        "entity_id": raw_header[7],
        "mac_address_and_entity_id": raw_header[:6] + raw_header[7:8],
        "command_type": raw_header[6]
    }


def process_serial_log_message(message):
    now = datetime.now()
    date_time = now.strftime("%H:%M:%S %m.%d.%Y")

    with open("/app/logfile.txt", "a") as log_file:
        log_file.write(date_time + "\t" + message + "\n")


def format_mqtt_rssi_config_topic(message, availability_topic):
    mqtt_config = json.loads(message.split("|")[1])

    mqtt_topic = "homeassistant" + message.split("|")[0][1:] + "onfig"

    mqtt_topic_splitted = mqtt_topic.split("/")
    mqtt_topic_splitted[1] = "sensor"
    mqtt_topic_splitted[2] = "rssi"
    mqtt_topic_splitted[3] = mqtt_config["d"]["i"] + "_rssi"

    mqtt_topic = "/".join(mqtt_topic_splitted).replace(" ", "_")

    mqtt_client_name = mqtt_topic_splitted[3]

    # TODO das irgendwie schöner gestalten und dynamisch machen
    if 'um' in mqtt_config:
        del mqtt_config['um']
    if 'dc' in mqtt_config:
        del mqtt_config['dc']
    if 'sc' in mqtt_config:
        del mqtt_config['sc']
    if 'mx' in mqtt_config:
        del mqtt_config['mx']
    if 'mn' in mqtt_config:
        del mqtt_config['mn']
    if 'st' in mqtt_config:
        del mqtt_config['st']
    if 'md' in mqtt_config:
        del mqtt_config['md']
    if 'o' in mqtt_config:
        del mqtt_config['o']

    del mqtt_config['n']
    mqtt_config['name'] = mqtt_config['d']['n'] + " RSSI"
    mqtt_config['unique_id'] = mqtt_client_name
    mqtt_config['object_id'] = mqtt_client_name
    mqtt_config['device_class'] = 'signal_strength'
    mqtt_config['state_class'] = 'measurement'
    mqtt_config['availability_topic'] = availability_topic
    mqtt_config['unit_of_measurement'] = 'dBm'
    mqtt_config['state_topic'] = mqtt_topic[:len(mqtt_topic) - 6] + "state"
    mqtt_config['device'] = expand_device_config(mqtt_config.pop('d'))

    # TODO das irgendwie schöner gestalten und dynamisch machen
    if 'seconds_until_timeout' in mqtt_config['device']:
        del mqtt_config['device']['seconds_until_timeout']

    # logging.debug("MQTT RSSI Config: %s", mqtt_config)

    return mqtt_topic, mqtt_config


class SerialTask:
    def __init__(self, influx_write_apis):
        self.influx_write_apis = influx_write_apis

        self.nowqtt_devices = NowqttDevices()

        self.config_message_request_cooldown = {}

    def request_config_message(self, header):
        self.config_message_request_cooldown[header["device_mac_address_int"]] = time.time()

        reset_message = header["device_mac_address_bytearray"]
        reset_message.append(0)
        reset_message.append(global_vars.SerialCommands.RESET.value)
        reset_message.append(0)
        global_vars.serial.write(reset_message + b'\n\n\n')

        logging.debug("request config on unknown state message")

    def process_mqtt_state_message(self, message, header):
        if self.nowqtt_devices.has_device_and_entity(header["device_mac_address_int"], header["entity_id"]):
            entity = self.nowqtt_devices.get_entity(header["device_mac_address_int"], header["entity_id"])
            entity.mqtt_publish(message)
        else:
            # Test if cooldown exists
            if header["device_mac_address_int"] in self.config_message_request_cooldown:
                # Test if cooldown is longer then five seconds ago
                if time.time() - self.config_message_request_cooldown[header["device_mac_address_int"]] >= global_vars.config["cooldown_between_config_request_on_unknown_sensor"]:
                    self.request_config_message(header)
            else:
                self.request_config_message(header)

    def process_mqtt_config_message(self, message, header):
        mqtt_topic = "homeassistant" + message.split("|")[0][1:]
        mqtt_message = message.split("|")[1]
        mqtt_client_name = mqtt_topic.split("/")[3]

        try:
            mqtt_config, seconds_until_timeout = expand_sensor_config(json.loads(mqtt_message), mqtt_client_name, mqtt_topic)

            if not self.nowqtt_devices.has_device_and_entity(header["device_mac_address_int"], header["entity_id"]):
                mqtt_subscriptions = ["homeassistant/status"]

                # If there is a command topic append it to the subscriptions
                if global_vars.platforms[mqtt_topic.split("/")[1]]['command']:
                    mqtt_subscriptions.append(mqtt_config["command_topic"])

                # Prepare RSSI MQTT
                mqtt_config_topic_rssi, mqtt_config_message_rssi = format_mqtt_rssi_config_topic(
                    message,
                    mqtt_config['availability_topic']
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
        if self.nowqtt_devices.has_device(header["device_mac_address_int"]):
            self.nowqtt_devices.devices[header["device_mac_address_int"]].rssi_entity.mqtt_publish(message)
        else:
            self.request_config_message(header)

    def process_serial_influx_message(self, message):
        message_dict = json.loads(message)

        organisation = message_dict["o"]
        p = Point(message_dict["mn"])
        bucket = message_dict["b"]

        for key, value in message_dict["items"].items():
            p.field(key, value)

        self.influx_write_apis[organisation].write(bucket=bucket, record=p)

    def process_serial_message(self, message, raw_header):
        header = expand_header_message(raw_header)
        print(header["device_mac_address_bytearray"].hex())
        print(header["mac_address_and_entity_id"].hex())
        print(header)

        # If device exists set last seen message
        if self.nowqtt_devices.has_device(header["device_mac_address_int"]):
            self.nowqtt_devices.set_last_seen_timestamp_to_now(header["device_mac_address_int"])

        # ESP has started. Disconnect and clear MQTT connections
        if header["command_type"] == global_vars.SerialCommands.RESET.value:
            self.nowqtt_devices.mqtt_disconnect_all()
            self.nowqtt_devices = NowqttDevices()
        # Influx insert message
        elif header["command_type"] == global_vars.SerialCommands.INFLUX.value:
            self.process_serial_influx_message(message)
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

        # clear the serial input buffer
        global_vars.serial.reset_input_buffer()

        logging.info("RUNNING")

        send_header = bytearray.fromhex("FF13AB06")
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

            message_length = int.from_bytes(global_vars.serial.read(1))
            if message_length == 0:
                raise TimeoutError("Partner Timeout")

            serial_header = global_vars.serial.read(8)
            logging.debug("Header: %s", serial_header.hex())

            serial_message = global_vars.serial.read(message_length-8).decode("utf-8", errors='ignore').strip()
            logging.debug("Message: %s", serial_message)
            self.process_serial_message(serial_message, serial_header)
