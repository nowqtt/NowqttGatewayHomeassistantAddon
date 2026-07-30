import itertools
import logging
import queue
import threading
import time
from enum import IntEnum


class SerialPriority(IntEnum):
    CONTROL = 0
    COMMAND = 10
    OTA = 20
    TRACE = 30


class SerialTransport:
    def __init__(self, serial_port, queue_size=256, reserved_high_priority_slots=16,
                 reserved_control_slots=4):
        if queue_size < 2:
            raise ValueError("Serial queue size must contain at least two slots")
        self._serial = serial_port
        self._outbound = queue.PriorityQueue(maxsize=queue_size)
        self._low_priority_limit = max(
            1, queue_size - min(reserved_high_priority_slots, queue_size - 1)
        )
        control_reserve = min(
            reserved_control_slots, max(1, queue_size // 8), queue_size - 1
        )
        self._non_control_limit = max(1, queue_size - control_reserve)
        self._sequence = itertools.count()
        self._admission_lock = threading.Lock()
        self._stop = threading.Event()
        self._accepting = threading.Event()
        self._accepting.set()
        self._drained = threading.Event()
        self._drained.set()
        self._write_failed = threading.Event()
        self._writer = threading.Thread(target=self._write_loop, name="serial-writer", daemon=True)
        self._metrics_lock = threading.Lock()
        self._metrics = {
            "frames_queued": 0,
            "frames_written": 0,
            "frames_dropped": 0,
            "write_errors": 0,
            "bytes_written": 0,
            "max_queue_depth": 0,
            "last_write_time": None,
        }

    def start(self):
        self._writer.start()

    def close(self, drain=True, timeout=5):
        with self._admission_lock:
            self._accepting.clear()
        if drain and self._writer.is_alive() and not self._write_failed.is_set():
            self._drained.wait(timeout)
        self._stop.set()
        self._writer.join(timeout=timeout)

    def send(self, frame, priority=SerialPriority.COMMAND):
        if not self._accepting.is_set() or self._write_failed.is_set():
            return False

        if not frame:
            raise ValueError("Cannot send an empty serial frame")
        with self._admission_lock:
            if not self._accepting.is_set() or self._write_failed.is_set():
                return False
            queue_depth = self._outbound.qsize()
            if priority > SerialPriority.CONTROL and queue_depth >= self._non_control_limit:
                self._increment_metric("frames_dropped")
                logging.warning(
                    "Serial control reserve is in use; dropping priority %d frame", priority
                )
                return False
            if priority >= SerialPriority.OTA and queue_depth >= self._low_priority_limit:
                self._increment_metric("frames_dropped")
                logging.warning("Serial low-priority capacity is full; dropping frame")
                return False

            item = (int(priority), next(self._sequence), bytes(frame))
            try:
                self._drained.clear()
                self._outbound.put_nowait(item)
            except queue.Full:
                if self._outbound.unfinished_tasks == 0:
                    self._drained.set()
                self._increment_metric("frames_dropped")
                logging.error(
                    "Serial output queue is full; dropping priority %d frame", priority
                )
                return False

        with self._metrics_lock:
            self._metrics["frames_queued"] += 1
            self._metrics["max_queue_depth"] = max(
                self._metrics["max_queue_depth"], self._outbound.qsize()
            )
        return True

    def read_exactly(self, size, allow_initial_timeout=False, deadline_seconds=2.0):
        if size < 0:
            raise ValueError("Serial read size cannot be negative")

        data = bytearray()
        deadline = time.monotonic() + deadline_seconds
        while len(data) < size:
            chunk = self._serial.read(size - len(data))
            if not chunk:
                if allow_initial_timeout and not data:
                    return None
                raise TimeoutError(
                    "Timed out after reading %d of %d serial bytes" % (len(data), size)
                )
            data.extend(chunk)
            if time.monotonic() > deadline:
                raise TimeoutError(
                    "Serial frame deadline expired after %d of %d bytes" % (len(data), size)
                )
        return bytes(data)

    def read_chunk(self, size=256):
        return self._serial.read(size)

    def writer_healthy(self):
        return self._writer.is_alive() and not self._write_failed.is_set()

    def snapshot_metrics(self):
        with self._metrics_lock:
            metrics = dict(self._metrics)
        metrics["queue_depth"] = self._outbound.qsize()
        metrics["writer_healthy"] = self.writer_healthy()
        metrics["accepting"] = self._accepting.is_set()
        return metrics

    def _increment_metric(self, name, amount=1):
        with self._metrics_lock:
            self._metrics[name] += amount

    def _write_loop(self):
        while not self._stop.is_set():
            try:
                _, _, frame = self._outbound.get(timeout=0.2)
            except queue.Empty:
                continue

            try:
                offset = 0
                while offset < len(frame):
                    written = self._serial.write(frame[offset:])
                    if not written:
                        raise TimeoutError("Serial write made no progress")
                    offset += written
                self._increment_metric("frames_written")
                self._increment_metric("bytes_written", len(frame))
                with self._metrics_lock:
                    self._metrics["last_write_time"] = time.time()
            except Exception:
                self._increment_metric("write_errors")
                self._write_failed.set()
                logging.exception("Serial writer stopped after an I/O error")
                return
            finally:
                self._outbound.task_done()
                if self._outbound.unfinished_tasks == 0:
                    self._drained.set()
