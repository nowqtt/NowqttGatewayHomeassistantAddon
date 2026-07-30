import logging
import time

import global_vars

from .nowqtt_device_tree import NowqttDevices
from .serial_send_helper import send_serial_message
from .serial_transport import SerialPriority


def _wait_for_next_trace(stop_event, interval):
    deadline = time.monotonic() + interval
    ota_seen = False
    while not stop_event.is_set():
        ota_active = global_vars.ota_coordinator.is_active()
        if ota_active:
            ota_seen = True
        elif ota_seen or time.monotonic() >= deadline:
            return True
        remaining = max(0, deadline - time.monotonic())
        wait_seconds = 1 if ota_active else min(1, remaining)
        if stop_event.wait(wait_seconds):
            return False
    return False

def trace_route_task(nowqtt_devices: NowqttDevices, lock, stop_event):
    while not stop_event.is_set():
        while global_vars.ota_coordinator.is_active():
            if stop_event.wait(1):
                return

        with lock:
            mac_address_list = nowqtt_devices.snapshot_addresses()

        paused_for_ota = False
        for device_mac_address in mac_address_list:
            if stop_event.is_set():
                return
            if global_vars.ota_coordinator.is_active():
                paused_for_ota = True
                break
            if not send_serial_message(
                "FF", device_mac_address, None, None, None, SerialPriority.TRACE
            ):
                logging.warning("Unable to queue trace request for %s", device_mac_address)
            else:
                logging.debug("Trace request %s", device_mac_address)

            if stop_event.wait(1):
                return

        if paused_for_ota:
            continue
        if not _wait_for_next_trace(
            stop_event, global_vars.config.get("trace_interval_seconds", 60)
        ):
            return
