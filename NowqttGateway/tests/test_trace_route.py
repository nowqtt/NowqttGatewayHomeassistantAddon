import pathlib
import sys
import unittest
from unittest import mock


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from gateway import trace_route_task


class FakeStopEvent:
    def __init__(self):
        self.waits = []

    def is_set(self):
        return False

    def wait(self, timeout):
        self.waits.append(timeout)
        return False


class TraceRouteWaitTests(unittest.TestCase):
    def test_active_ota_waits_instead_of_spinning_after_trace_deadline(self):
        stop_event = FakeStopEvent()
        coordinator = mock.Mock()
        coordinator.is_active.side_effect = [True, False]

        with mock.patch.object(
            trace_route_task.global_vars,
            "ota_coordinator",
            coordinator,
            create=True,
        ), mock.patch.object(
            trace_route_task.time,
            "monotonic",
            side_effect=[0, 2, 2],
        ):
            self.assertTrue(trace_route_task._wait_for_next_trace(stop_event, 1))

        self.assertEqual(stop_event.waits, [1])


if __name__ == "__main__":
    unittest.main()
