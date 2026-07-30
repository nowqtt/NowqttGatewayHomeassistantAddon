import logging
import math
import re
import threading
import time
from enum import IntEnum

from gateway.serial_send_helper import (
    send_ota_data_serial_message,
    send_ota_init_serial_message,
)


class OtaCommands(IntEnum):
    OTA_INIT = 101
    OTA_READY = 102
    OTA_DATA = 103
    OTA_RETRANSMIT = 104
    OTA_DISCOVER = 105
    OTA_DISCOVER_RESPONSE = 106


class OtaCoordinator:
    def __init__(self, max_firmware_size=4 * 1024 * 1024, session_timeout=1200):
        self._lock = threading.RLock()
        self._active = None
        self._max_firmware_size = max_firmware_size
        self._session_timeout = session_timeout
        self._last_status = None

    def start_update(self, firmware, mac_address):
        if not re.fullmatch(r"[0-9a-fA-F]{12}", mac_address or ""):
            raise ValueError("Device MAC address must contain exactly 12 hexadecimal digits")
        if not firmware:
            raise ValueError("Firmware image is empty")
        if len(firmware) > self._max_firmware_size:
            raise ValueError("Firmware image exceeds the configured OTA size limit")

        with self._lock:
            if self._active is not None:
                raise RuntimeError("Another OTA update is already active")
            session = OtaSession(
                bytes(firmware),
                mac_address.lower(),
                self._session_finished,
                self._session_timeout,
            )
            self._active = session
        session.start()
        return session.status()

    def handle_serial_message(self, mac_address, payload):
        with self._lock:
            session = self._active
        if session is None or session.mac_address != mac_address:
            logging.warning("Ignoring OTA message for inactive device %s", mac_address)
            return False
        return session.handle_serial_message(payload)

    def cancel(self):
        with self._lock:
            session = self._active
        if session is not None:
            session.cancel()

    def cancel_and_wait(self, timeout=5):
        with self._lock:
            session = self._active
        if session is not None:
            session.cancel()
            session.join(timeout)

    def is_active(self):
        with self._lock:
            return self._active is not None

    def status(self):
        with self._lock:
            session = self._active
        if session is None:
            if self._last_status is None:
                return {"active": False}
            return dict(self._last_status, active=False)
        return session.status()

    def _session_finished(self, session):
        with self._lock:
            self._last_status = session.status()
            if self._active is session:
                self._active = None


class OtaSession:
    payload_size = 232
    packet_delay_seconds = 0.05

    def __init__(self, firmware, mac_address, on_finished, session_timeout):
        self.firmware = firmware
        self.mac_address = mac_address
        self.packet_count = math.ceil(len(firmware) / self.payload_size)
        self._on_finished = on_finished
        self._session_timeout = session_timeout
        self._condition = threading.Condition()
        self._retransmit_packets = set()
        self._ready = False
        self._cancelled = False
        self._state = "initializing"
        self._sent_packets = 0
        self._deadline = None
        self._thread = threading.Thread(
            target=self._run,
            name="ota-%s" % mac_address,
            daemon=True,
        )

    def start(self):
        self._deadline = time.monotonic() + self._session_timeout
        self._thread.start()

    def join(self, timeout=None):
        self._thread.join(timeout)

    def cancel(self):
        with self._condition:
            self._cancelled = True
            self._condition.notify_all()

    def handle_serial_message(self, payload):
        if not payload:
            return False
        command = payload[0]
        with self._condition:
            if command == OtaCommands.OTA_READY:
                self._ready = True
                self._condition.notify_all()
                return True
            if command == OtaCommands.OTA_RETRANSMIT:
                if len(payload) != 5:
                    logging.warning("Ignoring malformed OTA retransmit message")
                    return False
                packet_number = int.from_bytes(payload[1:5], "little")
                if packet_number >= self.packet_count:
                    logging.warning("Ignoring out-of-range OTA packet %d", packet_number)
                    return False
                self._retransmit_packets.add(packet_number)
                self._condition.notify_all()
                return True
        return False

    def status(self):
        with self._condition:
            return {
                "active": self._state not in ("complete", "cancelled", "failed"),
                "device_mac_address": self.mac_address,
                "state": self._state,
                "packet_count": self.packet_count,
                "sent_packets": self._sent_packets,
            }

    def _run(self):
        try:
            if not send_ota_init_serial_message(
                "00", self.mac_address, OtaCommands.OTA_INIT, len(self.firmware)
            ):
                raise RuntimeError("Serial OTA initialization queue is full")

            with self._condition:
                ready = self._condition.wait_for(
                    lambda: self._ready or self._cancelled,
                    timeout=min(30, self._session_timeout),
                )
                if self._cancelled:
                    self._state = "cancelled"
                    return
                if not ready:
                    raise TimeoutError("Timed out waiting for OTA_READY")
                self._state = "sending"

            for packet_number in range(self.packet_count):
                self._check_active()
                self._send_packet(packet_number)

            quiet_deadline = time.monotonic() + 3
            with self._condition:
                self._state = "waiting_for_retransmits"

            while time.monotonic() < self._deadline:
                with self._condition:
                    if self._cancelled:
                        self._state = "cancelled"
                        return
                    timeout = max(0, min(quiet_deadline, self._deadline) - time.monotonic())
                    self._condition.wait(timeout=timeout)
                    packets = sorted(self._retransmit_packets)
                    self._retransmit_packets.clear()

                if packets:
                    quiet_deadline = time.monotonic() + 3
                    for packet_number in packets:
                        self._check_active()
                        self._send_packet(packet_number)
                    continue
                if time.monotonic() >= quiet_deadline:
                    with self._condition:
                        self._state = "complete"
                    logging.info("OTA transfer to %s completed", self.mac_address)
                    return

            raise TimeoutError("OTA retransmission window exceeded its deadline")
        except OtaCancelled:
            with self._condition:
                self._state = "cancelled"
            logging.info("OTA transfer to %s cancelled", self.mac_address)
        except Exception:
            with self._condition:
                self._state = "failed"
            logging.exception("OTA transfer to %s failed", self.mac_address)
        finally:
            self._on_finished(self)

    def _send_packet(self, packet_number):
        self._check_active()
        start = packet_number * self.payload_size
        payload = self.firmware[start:start + self.payload_size]
        if not payload:
            raise ValueError("Refusing to send an empty OTA packet")
        if not send_ota_data_serial_message(
            "00", self.mac_address, OtaCommands.OTA_DATA, packet_number, payload
        ):
            raise RuntimeError("Serial OTA queue is full")
        with self._condition:
            self._sent_packets += 1
            self._condition.wait_for(
                lambda: self._cancelled, timeout=self.packet_delay_seconds
            )
        self._check_active()

    def _check_active(self):
        with self._condition:
            if self._cancelled:
                self._state = "cancelled"
                raise OtaCancelled()
        if self._deadline is not None and time.monotonic() >= self._deadline:
            raise TimeoutError("OTA session deadline exceeded")


class OtaCancelled(Exception):
    pass
