import json
import pathlib
import sys
import unittest


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import global_vars
from gateway.formatter import (
    expand_sensor_config,
    format_mqtt_hop_count_config_topic,
    get_device_availability_topic,
    parse_discovery_topic,
)


class FormatterTests(unittest.TestCase):
    def setUp(self):
        global_vars.config = {"default_seconds_until_timeout": 60}
        self.header = {"device_mac_address": "c04e304b157e"}

    def test_actual_firmware_config_format(self):
        topic_part = "h/switch/nowqtt/smart_plug_TV_myRoom/c"
        mqtt_topic = "homeassistant/switch/nowqtt/smart_plug_TV_myRoom/c"
        config = json.loads(
            '{"name":"Smart plug TV my room","dev":'
            '{"ids":"ESP TV My Room","name":"ESP TV My Room"}}'
        )

        expanded, timeout = expand_sensor_config(
            config, "smart_plug_TV_myRoom", mqtt_topic, self.header
        )
        hop_topic, hop_config = format_mqtt_hop_count_config_topic(
            topic_part, expanded, self.header
        )

        self.assertEqual(timeout, 60)
        self.assertEqual(expanded["state_topic"], mqtt_topic[:-1] + "state")
        self.assertEqual(expanded["command_topic"], mqtt_topic + "om")
        self.assertEqual(
            expanded["availability_topic"],
            "homeassistant/available/ESP_TV_My_Room",
        )
        self.assertNotIn("availability", expanded)
        self.assertNotIn("availability_mode", expanded)
        self.assertEqual(
            get_device_availability_topic(expanded),
            expanded["availability_topic"],
        )
        self.assertTrue(hop_topic.endswith("/config"))
        self.assertIn("state_topic", hop_config)

    def test_discovery_topic_requires_exact_safe_segments(self):
        invalid_topics = [
            "h/switch/nowqtt/device/#/c",
            "h/switch/nowqtt/device/c/extra",
            "h/switch/nowqtt/device/command",
            "h/switch/bad namespace/device/c",
            "h/unsupported/nowqtt/device/c",
        ]
        for topic in invalid_topics:
            with self.subTest(topic=topic), self.assertRaises(ValueError):
                parse_discovery_topic(topic)


if __name__ == "__main__":
    unittest.main()
