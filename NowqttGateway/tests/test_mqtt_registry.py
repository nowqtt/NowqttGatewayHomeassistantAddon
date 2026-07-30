import pathlib
import sys
import threading
import types
import unittest


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

try:
    import paho.mqtt.client  # noqa: F401
except ModuleNotFoundError:
    paho = types.ModuleType("paho")
    paho.__path__ = []
    mqtt_package = types.ModuleType("paho.mqtt")
    mqtt_package.__path__ = []
    mqtt_client = types.ModuleType("paho.mqtt.client")
    paho.mqtt = mqtt_package
    mqtt_package.client = mqtt_client
    sys.modules["paho"] = paho
    sys.modules["paho.mqtt"] = mqtt_package
    sys.modules["paho.mqtt.client"] = mqtt_client

from gateway.mqtt_task import MQTTGateway


class FakeEntity:
    def __init__(self, key):
        self.key = key
        self.calls = []

    def publish_config(self):
        self.calls.append("config")

    def publish_availability(self, state):
        self.calls.append("availability:" + state)

    def republish_state(self):
        self.calls.append("state")


class MQTTRegistryTests(unittest.TestCase):
    def test_update_cancels_tombstone_for_current_config_topic(self):
        gateway = MQTTGateway.__new__(MQTTGateway)
        gateway._lock = threading.RLock()
        gateway._connected = threading.Event()
        gateway._pending_config_removals = {"homeassistant/sensor/current/config"}
        gateway._entities_by_command_topic = {}
        gateway.publish = lambda *args, **kwargs: True

        entity = types.SimpleNamespace(
            command_topic=None,
            config_topic="homeassistant/sensor/old/config",
            availability_topic="nowqtt/device/availability",
        )

        def update_config(config_topic, mqtt_config):
            old_config_topic = entity.config_topic
            old_availability_topic = entity.availability_topic
            entity.config_topic = config_topic
            entity.command_topic = None
            return old_config_topic, old_availability_topic

        entity.update_config = update_config
        entity.publish_config = lambda: None
        entity.publish_availability = lambda state: None

        gateway.update_entity(
            entity,
            "homeassistant/sensor/current/config",
            {},
        )

        self.assertNotIn(
            "homeassistant/sensor/current/config",
            gateway._pending_config_removals,
        )
        self.assertIn(
            "homeassistant/sensor/old/config",
            gateway._pending_config_removals,
        )

    def test_republish_skips_entity_replaced_after_snapshot(self):
        gateway = MQTTGateway.__new__(MQTTGateway)
        gateway._lock = threading.RLock()
        gateway._republish_timer = None
        gateway._started = True
        gateway._pending_config_removals = set()
        gateway._offline_availability_topics = set()

        old_entity = FakeEntity("device:1")
        new_entity = FakeEntity("device:1")
        gateway._entities_by_key = {old_entity.key: old_entity}

        def replace_during_management_publish():
            gateway._entities_by_key[old_entity.key] = new_entity

        gateway._publish_management_config = replace_during_management_publish
        gateway._republish_all()

        self.assertEqual(old_entity.calls, [])
        self.assertEqual(new_entity.calls, [])

    def test_republish_replays_retained_cleanup_before_management_config(self):
        gateway = MQTTGateway.__new__(MQTTGateway)
        gateway._lock = threading.RLock()
        gateway._republish_timer = None
        gateway._started = True
        gateway._entities_by_key = {}
        gateway._pending_config_removals = {"homeassistant/sensor/old/config"}
        gateway._offline_availability_topics = {"nowqtt/device/offline"}

        calls = []
        gateway.publish = lambda topic, payload, qos=0, retain=False: calls.append(
            (topic, payload, qos, retain)
        )
        gateway._publish_management_config = lambda: calls.append(("management",))

        gateway._republish_all()

        self.assertEqual(calls, [
            ("homeassistant/sensor/old/config", "", 1, True),
            ("nowqtt/device/offline", "offline", 1, True),
            ("management",),
        ])


if __name__ == "__main__":
    unittest.main()
