import json
import logging
import re

import global_vars


GATEWAY_AVAILABILITY_TOPIC = "homeassistant/available/NowQtt"
SAFE_TOPIC_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def parse_discovery_topic(topic_part):
    if not isinstance(topic_part, str) or len(topic_part) > 512:
        raise ValueError("MQTT discovery topic is invalid")
    if "+" in topic_part or "#" in topic_part:
        raise ValueError("MQTT discovery topic cannot contain wildcards")
    if any(ord(character) < 32 or ord(character) == 127 for character in topic_part):
        raise ValueError("MQTT discovery topic cannot contain control characters")

    segments = topic_part.split("/")
    if len(segments) != 5 or segments[0] != "h" or segments[4] != "c":
        raise ValueError(
            "MQTT discovery topic must match h/<platform>/<namespace>/<object>/c"
        )
    platform, namespace, object_id = segments[1:4]
    if platform not in global_vars.platforms:
        raise ValueError("Unsupported MQTT platform %s" % platform)
    for field_name, value in (("namespace", namespace), ("object", object_id)):
        if not SAFE_TOPIC_SEGMENT.fullmatch(value):
            raise ValueError("MQTT discovery %s contains unsafe characters" % field_name)

    mqtt_topic = "homeassistant/" + "/".join(segments[1:])
    return platform, namespace, object_id, mqtt_topic


def _safe_device_id(value):
    if not isinstance(value, str):
        raise ValueError("MQTT device config must contain a string ids field")
    normalized = value.replace(" ", "_")
    if not SAFE_TOPIC_SEGMENT.fullmatch(normalized):
        raise ValueError("MQTT device ids contains unsafe characters")
    return normalized


def get_device_availability_topic(mqtt_config):
    availability = mqtt_config.get('availability', [])
    if len(availability) < 2:
        raise ValueError("MQTT config is missing device availability")
    return availability[1]['topic']


def expand_sensor_config(mqtt_config, mqtt_client_name, mqtt_topic, header):
    topic_segments = mqtt_topic.split("/")
    if (
        len(topic_segments) != 5
        or topic_segments[0] != "homeassistant"
        or topic_segments[4] != "c"
    ):
        raise ValueError("MQTT discovery topic is incomplete")
    platform = topic_segments[1]
    if platform not in global_vars.platforms:
        raise ValueError("Unsupported MQTT platform %s" % platform)
    if not isinstance(mqtt_config, dict) or not isinstance(mqtt_config.get('dev'), dict):
        raise ValueError("MQTT config must contain a device object")
    device_topic_id = _safe_device_id(mqtt_config['dev'].get('ids'))
    if (
        not isinstance(mqtt_config['dev'].get('name'), str)
        or not mqtt_config['dev']['name'].strip()
        or len(mqtt_config['dev']['name']) > 128
        or any(ord(character) < 32 for character in mqtt_config['dev']['name'])
    ):
        raise ValueError("MQTT device config must contain a string name field")

    mqtt_config['unique_id'] = mqtt_client_name
    mqtt_config['object_id'] = mqtt_client_name

    if global_vars.platforms[platform]['state']:
        mqtt_config['state_topic'] = mqtt_topic[:len(mqtt_topic) - 1] + "state"
    if global_vars.platforms[platform]['command']:
        mqtt_config['command_topic'] = mqtt_topic + "om"

    seconds_until_timeout = global_vars.config["default_seconds_until_timeout"]
    if 'sut' in mqtt_config['dev']:
        seconds_until_timeout = mqtt_config['dev'].pop('sut')
    if not isinstance(seconds_until_timeout, (int, float)) or seconds_until_timeout <= 0:
        raise ValueError("Device timeout must be a positive number")

    mqtt_config['dev']['manufacturer'] = "nowqtt"
    mqtt_config['dev']['model'] = header["device_mac_address"]

    device_availability_topic = (
        "homeassistant/available/" + device_topic_id
    )
    mqtt_config['availability'] = [
        {'topic': GATEWAY_AVAILABILITY_TOPIC},
        {'topic': device_availability_topic},
    ]
    mqtt_config['availability_mode'] = 'all'

    logging.debug("MQTT Config: %s", mqtt_config)
    return mqtt_config, seconds_until_timeout


def expand_header_message(raw_header):
    return {
        "device_mac_address": raw_header[:6].hex(),
        "device_mac_address_and_entity_id": (raw_header[:6] + raw_header[7:8]).hex(),
        "entity_id": raw_header[7],
        "command_type": raw_header[6]
    }


def format_mqtt_hop_count_config_topic(topic_part, mqtt_config, header):
    mqtt_config = json.loads(json.dumps(mqtt_config))
    parse_discovery_topic(topic_part)
    mqtt_client_name = _safe_device_id(mqtt_config["dev"]["ids"]) + "_hopCount"
    mqtt_topic = "homeassistant/sensor/hopCount/%s/config" % mqtt_client_name

    keys_to_delete = []
    for key, value in mqtt_config.items():
        if key not in ['dev']:
            keys_to_delete.append(key)

    for key in keys_to_delete:
        del mqtt_config[key]

    mqtt_config['name'] = mqtt_config['dev']['name'] + " Hop Count"
    mqtt_config['unique_id'] = mqtt_client_name
    mqtt_config['object_id'] = mqtt_client_name
    mqtt_config['state_topic'] = mqtt_topic[:-6] + "state"

    mqtt_config['dev'].pop('sut', None)

    mqtt_config['dev']['manufacturer'] = "nowqtt"
    mqtt_config['dev']['model'] = header["device_mac_address"]

    logging.debug("MQTT hop count config: %s", mqtt_config)

    return mqtt_topic, mqtt_config
