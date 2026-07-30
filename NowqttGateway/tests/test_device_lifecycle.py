import contextlib
import pathlib
import sys
import threading
import unittest
from unittest.mock import patch


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from gateway.mqtt_sensor_available_task import mqtt_sensor_available_task
from gateway.nowqtt_device_tree import Device, NowqttDevices


class FakeEntity:
    def __init__(self):
        self.availability = []

    def publish_availability(self, state):
        self.availability.append(state)


class FakeGateway:
    def __init__(self):
        self.entities = {}

    def unregister_entity(self, key, expected_entity=None, publish_availability=True):
        current = self.entities.get(key)
        if current is not expected_entity:
            return False
        self.entities.pop(key)
        if publish_availability:
            current.publish_availability("offline")
        return True


class StopAfterOneIteration:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, timeout):
        self.stopped = True
        return True


class AvailabilityTree:
    def __init__(self, mac_address, old_device):
        self.devices = {mac_address: object()}
        self.mac_address = mac_address
        self.old_device = old_device
        self.disconnect_calls = []

    def pop_timed_out(self, now):
        return [(self.mac_address, self.old_device)]

    def lifecycle_lock(self, mac_address):
        return contextlib.nullcontext()

    def has_device(self, mac_address):
        return mac_address in self.devices

    def disconnect_device(self, mac_address, device, publish_availability=True):
        self.disconnect_calls.append((mac_address, device, publish_availability))


class DeviceLifecycleTests(unittest.TestCase):
    def test_stale_device_cannot_unregister_or_offline_replacement_entities(self):
        mac_address = "aabbccddeeff"
        gateway = FakeGateway()
        devices = NowqttDevices(gateway)

        old_hop = FakeEntity()
        old_entity = FakeEntity()
        old_device = Device(60, old_hop, mac_address + ":hop")
        old_device.entities[1] = old_entity
        old_device.entity_keys[1] = mac_address + ":1"

        new_hop = FakeEntity()
        new_entity = FakeEntity()
        gateway.entities = {
            mac_address + ":hop": new_hop,
            mac_address + ":1": new_entity,
        }

        with patch("gateway.nowqtt_device_tree.insert_device_activity_table") as activity:
            removed = devices.disconnect_device(
                mac_address, old_device, publish_availability=False
            )

        self.assertFalse(removed)
        self.assertEqual(gateway.entities[mac_address + ":hop"], new_hop)
        self.assertEqual(gateway.entities[mac_address + ":1"], new_entity)
        self.assertEqual(old_hop.availability, [])
        self.assertEqual(old_entity.availability, [])
        activity.assert_not_called()

    def test_availability_cleanup_detects_a_replacement_generation(self):
        mac_address = "aabbccddeeff"
        old_device = object()
        devices = AvailabilityTree(mac_address, old_device)

        mqtt_sensor_available_task(
            devices,
            threading.RLock(),
            StopAfterOneIteration(),
        )

        self.assertEqual(
            devices.disconnect_calls,
            [(mac_address, old_device, False)],
        )


if __name__ == "__main__":
    unittest.main()
