import json
import math


OTA_PACKET_PAYLOAD_SIZE = 232
OTA_PACKET_DELAY_SECONDS = 0.05
OTA_HANDSHAKE_AND_COMPLETION_SECONDS = 33


def load_config(options_path):
    with open(options_path, "r", encoding="utf-8") as options_file:
        config = json.load(options_file)

    config.setdefault("trace_interval_seconds", 60)
    config.setdefault("trace_retention_days", 30)
    config.setdefault("serial_read_timeout_seconds", 1.0)
    config.setdefault("serial_write_timeout_seconds", 2.0)
    config.setdefault("serial_output_queue_size", 256)
    config.setdefault("max_ota_firmware_size", 4 * 1024 * 1024)
    config.setdefault("ota_session_timeout_seconds", 1200)
    return validate_config(config)


def validate_config(config):
    if not isinstance(config, dict):
        raise ValueError("Add-on options must be a JSON object")

    allowed_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    log_level = config.get("log_level")
    if log_level not in allowed_log_levels:
        raise ValueError("log_level must be one of %s" % ", ".join(sorted(allowed_log_levels)))

    def positive_number(name, minimum=0, maximum=None):
        value = config.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("%s must be a number" % name)
        if value <= minimum or (maximum is not None and value > maximum):
            if maximum is None:
                raise ValueError("%s must be greater than %s" % (name, minimum))
            raise ValueError("%s must be greater than %s and at most %s" % (
                name, minimum, maximum
            ))

    positive_number("default_seconds_until_timeout")
    positive_number("cooldown_between_config_request_on_unknown_sensor")
    positive_number("trace_interval_seconds")
    positive_number("trace_retention_days")
    positive_number("serial_read_timeout_seconds")
    positive_number("serial_write_timeout_seconds")
    positive_number("serial_output_queue_size", 1, 4096)
    positive_number("max_ota_firmware_size", 0, 4 * 1024 * 1024)
    positive_number("ota_session_timeout_seconds", 29, 3600)
    minimum_ota_timeout = (
        math.ceil(config["max_ota_firmware_size"] / OTA_PACKET_PAYLOAD_SIZE)
        * OTA_PACKET_DELAY_SECONDS
        + OTA_HANDSHAKE_AND_COMPLETION_SECONDS
    )
    if config["ota_session_timeout_seconds"] < minimum_ota_timeout:
        raise ValueError(
            "ota_session_timeout_seconds must be at least %d for the configured "
            "max_ota_firmware_size" % math.ceil(minimum_ota_timeout)
        )

    serial_config = config.get("serial")
    if not isinstance(serial_config, dict):
        raise ValueError("serial must be an object")
    if not isinstance(serial_config.get("com_port"), str) or not serial_config["com_port"].strip():
        raise ValueError("serial.com_port must be a non-empty string")
    baudrate = serial_config.get("baudrate")
    if isinstance(baudrate, bool) or not isinstance(baudrate, int) or baudrate <= 0:
        raise ValueError("serial.baudrate must be a positive integer")

    mqtt_config = config.get("mqtt_client")
    if not isinstance(mqtt_config, dict):
        raise ValueError("mqtt_client must be an object")
    if not isinstance(mqtt_config.get("address"), str) or not mqtt_config["address"].strip():
        raise ValueError("mqtt_client.address must be a non-empty string")
    port = mqtt_config.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("mqtt_client.port must be between 1 and 65535")
    for credential in ("username", "password"):
        if not isinstance(mqtt_config.get(credential), str):
            raise ValueError("mqtt_client.%s must be a string" % credential)
    return config
