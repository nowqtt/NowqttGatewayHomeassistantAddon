import pathlib
import sys
import threading
import unittest


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from gateway.serial_transport import SerialPriority, SerialTransport


class FakeSerial:
    def __init__(self, chunks=None, partial_write_size=None):
        self.chunks = list(chunks or [])
        self.partial_write_size = partial_write_size
        self.written = bytearray()
        self.write_event = threading.Event()

    def read(self, size):
        if not self.chunks:
            return b""
        chunk = self.chunks.pop(0)
        if len(chunk) > size:
            self.chunks.insert(0, chunk[size:])
            return chunk[:size]
        return chunk

    def write(self, data):
        size = len(data) if self.partial_write_size is None else min(
            len(data), self.partial_write_size
        )
        self.written.extend(data[:size])
        self.write_event.set()
        return size


class SerialTransportTests(unittest.TestCase):
    def test_read_exactly_combines_fragmented_reads(self):
        transport = SerialTransport(FakeSerial([b"a", b"bc", b"def"]))
        self.assertEqual(transport.read_exactly(6), b"abcdef")

    def test_idle_read_can_timeout_without_becoming_a_frame_error(self):
        transport = SerialTransport(FakeSerial())
        self.assertIsNone(transport.read_exactly(1, allow_initial_timeout=True))

    def test_partial_read_timeout_is_reported(self):
        transport = SerialTransport(FakeSerial([b"ab"]))
        with self.assertRaises(TimeoutError):
            transport.read_exactly(3)

    def test_writer_handles_partial_writes(self):
        serial_port = FakeSerial(partial_write_size=2)
        transport = SerialTransport(serial_port)
        transport.start()
        self.assertTrue(transport.send(b"abcdef"))
        self.assertTrue(serial_port.write_event.wait(timeout=1))
        transport._outbound.join()
        transport.close()
        self.assertEqual(serial_port.written, b"abcdef")
        self.assertEqual(transport.snapshot_metrics()["frames_written"], 1)

    def test_low_priority_frames_cannot_consume_command_reserve(self):
        transport = SerialTransport(FakeSerial(), queue_size=4, reserved_high_priority_slots=2)
        self.assertTrue(transport.send(b"trace-1", SerialPriority.TRACE))
        self.assertTrue(transport.send(b"trace-2", SerialPriority.OTA))
        self.assertFalse(transport.send(b"trace-3", SerialPriority.TRACE))
        self.assertTrue(transport.send(b"command", SerialPriority.COMMAND))
        self.assertEqual(transport.snapshot_metrics()["frames_dropped"], 1)

    def test_non_control_frames_cannot_consume_control_reserve(self):
        transport = SerialTransport(
            FakeSerial(), queue_size=4, reserved_high_priority_slots=1,
            reserved_control_slots=1,
        )
        self.assertTrue(transport.send(b"command-1", SerialPriority.COMMAND))
        self.assertTrue(transport.send(b"command-2", SerialPriority.COMMAND))
        self.assertTrue(transport.send(b"command-3", SerialPriority.COMMAND))
        self.assertFalse(transport.send(b"command-4", SerialPriority.COMMAND))
        self.assertTrue(transport.send(b"control", SerialPriority.CONTROL))


if __name__ == "__main__":
    unittest.main()
