import json
import logging

import global_vars


def expand_sensor_config(mqtt_config, mqtt_client_name, mqtt_topic, header):
    platform = mqtt_topic.split("/")[1]

    mqtt_config['unique_id'] = mqtt_client_name
    mqtt_config['object_id'] = mqtt_client_name

    if global_vars.platforms[platform]['state']:
        mqtt_config['state_topic'] = mqtt_topic[:len(mqtt_topic) - 1] + "state"
    if global_vars.platforms[platform]['command']:
        mqtt_config['command_topic'] = mqtt_topic + "om"

    seconds_until_timeout = global_vars.config["default_seconds_until_timeout"]
    if 'sut' in mqtt_config['dev']:
        seconds_until_timeout = mqtt_config['dev'].pop('sut')

    mqtt_config['dev']['manufacturer'] = "nowqtt"
    mqtt_config['dev']['model'] = header["device_mac_address"]

    mqtt_config['availability_topic'] = ("homeassistant/available/" +
                                         mqtt_config['dev']['ids'].replace(" ", "_"))

    logging.debug("MQTT Config: %s", mqtt_config)
    return mqtt_config, seconds_until_timeout


def expand_header_message(raw_header):
    return {
        "device_mac_address": raw_header[:6].hex(),
        "device_mac_address_and_entity_id": (raw_header[:6] + raw_header[7:8]).hex(),
        "entity_id": raw_header[7],
        "command_type": raw_header[6]
    }


def format_mqtt_rssi_config_topic(message, availability_topic, header):
    mqtt_config = json.loads(message.split("|")[1])

    mqtt_topic = "homeassistant" + message.split("|")[0][1:] + "onfig"

    mqtt_topic_splitted = mqtt_topic.split("/")
    mqtt_topic_splitted[1] = "sensor"
    mqtt_topic_splitted[2] = "rssi"
    mqtt_topic_splitted[3] = mqtt_config["dev"]["ids"] + "_rssi"

    mqtt_topic = "/".join(mqtt_topic_splitted).replace(" ", "_")

    mqtt_client_name = mqtt_topic_splitted[3]

    keys_to_delete = []
    for key, value in mqtt_config.items():
        if key not in ['dev']:
            keys_to_delete.append(key)

    for key in keys_to_delete:
        del mqtt_config[key]

    mqtt_config['name'] = mqtt_config['dev']['name'] + " RSSI"
    mqtt_config['unique_id'] = mqtt_client_name
    mqtt_config['object_id'] = mqtt_client_name
    mqtt_config['device_class'] = 'signal_strength'
    mqtt_config['state_class'] = 'measurement'
    mqtt_config['availability_topic'] = availability_topic
    mqtt_config['unit_of_measurement'] = 'dBm'
    mqtt_config['state_topic'] = mqtt_topic[:len(mqtt_topic) - 6] + "state"

    if 'sut' in mqtt_config['dev']:
        del mqtt_config['dev']['seconds_until_timeout']

    mqtt_config['dev']['manufacturer'] = "nowqtt"
    mqtt_config['dev']['model'] = header["device_mac_address"]

    logging.debug("MQTT RSSI Config: %s", mqtt_config)

    return mqtt_topic, mqtt_config
