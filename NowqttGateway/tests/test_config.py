import pathlib
import sys
import unittest


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from configuration import validate_config


def valid_config():
    return {
        "log_level": "INFO",
        "default_seconds_until_timeout": 60,
        "cooldown_between_config_request_on_unknown_sensor": 5,
        "trace_interval_seconds": 60,
        "trace_retention_days": 30,
        "serial_read_timeout_seconds": 1,
        "serial_write_timeout_seconds": 2,
        "serial_output_queue_size": 256,
        "max_ota_firmware_size": 4 * 1024 * 1024,
        "ota_session_timeout_seconds": 1200,
        "serial": {"com_port": "/dev/ttyACM0", "baudrate": 115200},
        "mqtt_client": {
            "username": "",
            "password": "",
            "address": "mqtt",
            "port": 1883,
        },
    }


class ConfigTests(unittest.TestCase):
    def test_valid_config_is_accepted(self):
        config = valid_config()
        self.assertIs(validate_config(config), config)

    def test_empty_mqtt_address_is_rejected(self):
        config = valid_config()
        config["mqtt_client"]["address"] = ""
        with self.assertRaisesRegex(ValueError, "mqtt_client.address"):
            validate_config(config)

    def test_non_positive_timeout_is_rejected(self):
        config = valid_config()
        config["serial_read_timeout_seconds"] = 0
        with self.assertRaisesRegex(ValueError, "serial_read_timeout_seconds"):
            validate_config(config)

    def test_invalid_log_level_is_rejected(self):
        config = valid_config()
        config["log_level"] = "TEST"
        with self.assertRaisesRegex(ValueError, "log_level"):
            validate_config(config)

    def test_ota_timeout_must_cover_maximum_firmware_pacing(self):
        config = valid_config()
        config["ota_session_timeout_seconds"] = 300
        with self.assertRaisesRegex(ValueError, "must be at least"):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
