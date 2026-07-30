from collections import OrderedDict
import json
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import global_vars

from nowqtt_database import (
    find_device_names,
    insert_device_activity_table,
    insert_devices_names,
    insert_trace_with_hops,
    update_devices_names,
)

from .formatter import (
    expand_header_message,
    expand_sensor_config,
    format_mqtt_hop_count_config_topic,
    parse_discovery_topic,
)
from .managed_worker import ManagedWorker
from .mqtt_sensor_available_task import mqtt_sensor_available_task
from .nowqtt_device_tree import NowqttDevices
from .serial_send_helper import send_serial_message
from .serial_framing import SerialFrameReader
from .serial_transport import SerialPriority
from .trace_route_task import trace_route_task


MAX_CONFIG_COOLDOWN_ENTRIES = 1024
NOWQTT_HEADER_SIZE = 8
TRACE_HEADER_SIZE = 6
TRACE_HOP_SIZE = 13


def process_serial_log_message(message):
    logging.info(message)
    try:
        with open("/app/logfile.txt", "a", encoding="utf-8") as log_file:
            log_file.write(
                datetime.now().strftime("%H:%M:%S %m.%d.%Y") + "\t" + message + "\n"
            )
    except OSError:
        logging.exception("Unable to append device log")


def calculate_hop_count_to_and_from(mac_address, hops):
    destination_index = next(
        (index for index, hop in enumerate(hops) if hop["hop_mac_address"] == mac_address),
        None,
    )
    if destination_index is None:
        return "%d/-1" % max(-1, len(hops) - 1)
    return "%d/%d" % (max(-1, destination_index - 1), len(hops) - destination_index - 1)


class SerialTask:
    def __init__(self, mqtt_gateway, stop_event=None):
        self.nowqtt_devices = NowqttDevices(mqtt_gateway)
        self.config_message_request_cooldown = OrderedDict()
        self.lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="frame-dispatch")
        self._dispatch_slots = threading.BoundedSemaphore(64)
        self._stopping = stop_event or threading.Event()
        self._closed = threading.Event()
        self._running = threading.Event()
        self._background_workers = []
        self._frame_reader = SerialFrameReader(global_vars.serial_transport.read_chunk)
        self._metrics_lock = threading.Lock()
        self._metrics = {
            "frames_received": 0,
            "frames_rejected": 0,
            "frame_timeouts": 0,
            "dispatch_dropped": 0,
            "last_frame_time": None,
        }

    def start_serial_task(self):
        self._start_background_tasks()
        global_vars.serial.reset_input_buffer()
        logging.info("Serial task running")
        self._running.set()

        try:
            while not self._stopping.is_set():
                if not global_vars.serial_transport.writer_healthy():
                    raise OSError("Serial writer has stopped")
                self._raise_worker_failure()
                try:
                    self._read_one_frame()
                except TimeoutError as error:
                    self._increment_metric("frame_timeouts")
                    logging.warning("Serial frame timeout; resynchronizing: %s", error)
                except (ValueError, json.JSONDecodeError):
                    self._increment_metric("frames_rejected")
                    logging.warning("Rejected malformed serial frame", exc_info=True)
                except OSError:
                    logging.exception("Fatal serial transport failure")
                    raise
                except Exception:
                    self._increment_metric("frames_rejected")
                    logging.exception("Rejected malformed serial frame")
        finally:
            self._running.clear()

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        self._stopping.set()
        for worker in self._background_workers:
            worker.join(timeout=2)
        self._executor.shutdown(wait=True)
        with self.lock:
            devices = list(self.nowqtt_devices.devices.items())
            self.nowqtt_devices.devices.clear()
        for mac_address, device in devices:
            self.nowqtt_devices.disconnect_device(mac_address, device)

    def snapshot_metrics(self):
        with self._metrics_lock:
            metrics = dict(self._metrics)
        metrics["running"] = self._running.is_set()
        metrics["workers"] = self.worker_status()
        return metrics

    def worker_status(self):
        return {worker.name: worker.status() for worker in self._background_workers}

    def failure(self):
        for worker in self._background_workers:
            failure = worker.failure()
            if failure is not None:
                return "%s: %s" % (worker.name, failure)
        return None

    def _start_background_tasks(self):
        self._background_workers = [
            ManagedWorker(
                "device-availability",
                mqtt_sensor_available_task,
                self._stopping,
                (self.nowqtt_devices, self.lock),
            ),
            ManagedWorker(
                "trace-routes",
                trace_route_task,
                self._stopping,
                (self.nowqtt_devices, self.lock),
            ),
        ]
        for worker in self._background_workers:
            worker.start()

    def _raise_worker_failure(self):
        failure = self.failure()
        if failure is not None:
            raise RuntimeError("Required serial worker failed: %s" % failure)

    def _read_one_frame(self):
        frame = self._frame_reader.read_frame()
        if frame is None:
            return False
        service, body = frame

        self._increment_metric("frames_received")
        with self._metrics_lock:
            self._metrics["last_frame_time"] = time.time()

        if service == 0xFF:
            self._parse_trace(body)
        elif service == 0x00:
            self._parse_ota(body)
        else:
            self._parse_nowqtt(body)
        return True

    def _parse_trace(self, body):
        if len(body) < TRACE_HEADER_SIZE:
            raise ValueError("Trace frame is shorter than its header")
        payload = body[TRACE_HEADER_SIZE:]
        if len(payload) % TRACE_HOP_SIZE:
            raise ValueError("Trace payload has a partial hop")

        destination = body[:TRACE_HEADER_SIZE].hex()
        hops = []
        for hop_counter, offset in enumerate(range(0, len(payload), TRACE_HOP_SIZE)):
            raw_hop = payload[offset:offset + TRACE_HOP_SIZE]
            hops.append({
                "hop_counter": hop_counter,
                "hop_mac_address": raw_hop[:6].hex(),
                "hop_rssi": int.from_bytes(raw_hop[6:7], "little", signed=True),
                "hop_dest_seq": int.from_bytes(raw_hop[7:11], "little"),
                "route_age": raw_hop[11],
                "hop_count": raw_hop[12],
            })

        trace_uuid = str(uuid.uuid4())
        self._submit(
            self._store_trace_and_publish,
            destination,
            trace_uuid,
            hops,
        )

    def _store_trace_and_publish(self, destination, trace_uuid, hops):
        if not insert_trace_with_hops(destination, trace_uuid, hops):
            return
        with self.lock:
            device = self.nowqtt_devices.devices.get(destination)
            hop_entity = device.hop_count_entity if device is not None else None
        if hop_entity is not None:
            hop_entity.publish_state(calculate_hop_count_to_and_from(destination, hops))

    def _parse_ota(self, body):
        if len(body) < 6:
            raise ValueError("OTA frame is shorter than its source address")
        mac_address = body[:6].hex()
        payload = body[6:]
        if not payload:
            raise ValueError("OTA frame has no command")
        global_vars.ota_coordinator.handle_serial_message(mac_address, payload)

    def _parse_nowqtt(self, body):
        if len(body) < NOWQTT_HEADER_SIZE:
            raise ValueError("Nowqtt frame is shorter than its header")
        header = expand_header_message(body[:NOWQTT_HEADER_SIZE])
        payload = body[NOWQTT_HEADER_SIZE:]
        try:
            message = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise ValueError("Nowqtt payload is not valid UTF-8") from error
        self._submit(self._process_serial_message, message, header)

    def _submit(self, function, *args):
        if not self._dispatch_slots.acquire(blocking=False):
            self._increment_metric("dispatch_dropped")
            logging.error("Frame dispatch queue is full; dropping frame")
            return False

        future = self._executor.submit(function, *args)
        future.add_done_callback(self._dispatch_done)
        return True

    def _dispatch_done(self, future):
        self._dispatch_slots.release()
        try:
            future.result()
        except Exception:
            logging.exception("Serial frame dispatch failed")

    def _process_serial_message(self, message, header):
        device_mac = header["device_mac_address"]
        with self.lock:
            self.nowqtt_devices.set_last_seen_timestamp_to_now(device_mac)

        command_type = header["command_type"]
        if command_type == global_vars.SerialCommands.STATE.value:
            self._process_mqtt_state_message(message, header)
        elif command_type == global_vars.SerialCommands.CONFIG.value:
            self._process_mqtt_config_message(message, header)
        elif command_type == global_vars.SerialCommands.LOG.value:
            process_serial_log_message(message)
        elif command_type == global_vars.SerialCommands.HEARTBEAT.value:
            self._process_heartbeat(header)
        else:
            raise ValueError("Unknown Nowqtt command type %d" % command_type)

    def _process_mqtt_state_message(self, message, header):
        with self.lock:
            if self.nowqtt_devices.has_device_and_entity(
                header["device_mac_address"], header["entity_id"]
            ):
                entity = self.nowqtt_devices.get_entity(
                    header["device_mac_address"], header["entity_id"]
                )
            else:
                entity = None
                should_request = self._should_request_config(header["device_mac_address"])

        if entity is not None:
            entity.publish_state(message)
        elif should_request:
            self._request_config_message(header)

    def _process_mqtt_config_message(self, message, header):
        topic_part, separator, mqtt_message = message.partition("|")
        if not separator:
            raise ValueError("Config message does not contain a valid topic separator")

        _, _, mqtt_client_name, mqtt_topic = parse_discovery_topic(topic_part)
        config_topic = mqtt_topic[:-1] + "config"

        mqtt_config = json.loads(mqtt_message)
        mqtt_config, seconds_until_timeout = expand_sensor_config(
            mqtt_config, mqtt_client_name, mqtt_topic, header
        )
        self._write_device_name(header["device_mac_address"], mqtt_config["dev"]["name"])

        mqtt_config_topic_hop_count, mqtt_config_message_hop_count = (
            format_mqtt_hop_count_config_topic(
                topic_part, mqtt_config, header
            )
        )

        device_mac_address = header["device_mac_address"]
        with self.nowqtt_devices.lifecycle_lock(device_mac_address):
            with self.lock:
                needs_hop_entity, needs_entity = self.nowqtt_devices.registration_needs(
                    device_mac_address, header["entity_id"]
                )

            hop_entity = None
            if needs_hop_entity:
                hop_entity = self.nowqtt_devices.prepare_hop_entity(
                    device_mac_address,
                    mqtt_config_topic_hop_count,
                    mqtt_config_message_hop_count,
                )
            entity = None
            if needs_entity:
                entity = self.nowqtt_devices.prepare_entity(
                    header, config_topic, mqtt_config
                )

            with self.lock:
                device, attached_entity, is_new_device = self.nowqtt_devices.attach_element(
                    header,
                    seconds_until_timeout,
                    hop_entity,
                    entity,
                )

            if not needs_hop_entity:
                self.nowqtt_devices.update_hop_entity(
                    device,
                    mqtt_config_topic_hop_count,
                    mqtt_config_message_hop_count,
                )
            if not needs_entity:
                self.nowqtt_devices.update_entity(
                    header, attached_entity, config_topic, mqtt_config
                )
            if is_new_device:
                device.hop_count_entity.publish_availability("online")
                insert_device_activity_table(device_mac_address, 1)

    def _process_heartbeat(self, header):
        with self.lock:
            known = self.nowqtt_devices.has_device(header["device_mac_address"])
        if not known and self._should_request_config(header["device_mac_address"]):
            self._request_config_message(header)

    def _should_request_config(self, device_mac_address):
        now = time.monotonic()
        cooldown = global_vars.config["cooldown_between_config_request_on_unknown_sensor"]
        while self.config_message_request_cooldown:
            _, oldest_request = next(iter(self.config_message_request_cooldown.items()))
            if now - oldest_request < cooldown:
                break
            self.config_message_request_cooldown.popitem(last=False)

        last_request = self.config_message_request_cooldown.get(device_mac_address)
        if last_request is not None and now - last_request < cooldown:
            return False
        self.config_message_request_cooldown[device_mac_address] = now
        self.config_message_request_cooldown.move_to_end(device_mac_address)
        while len(self.config_message_request_cooldown) > MAX_CONFIG_COOLDOWN_ENTRIES:
            self.config_message_request_cooldown.popitem(last=False)
        return True

    @staticmethod
    def _request_config_message(header):
        if not send_serial_message(
            "01",
            header["device_mac_address"],
            global_vars.SerialCommands.RESET.value,
            0,
            None,
            SerialPriority.CONTROL,
        ):
            logging.error(
                "Unable to queue config request for %s", header["device_mac_address"]
            )

    @staticmethod
    def _write_device_name(mac_address, device_name):
        rows = find_device_names(mac_address)
        if rows:
            if rows[0][2] == 0:
                update_devices_names(mac_address, device_name, 0)
        else:
            insert_devices_names(mac_address, device_name, 0)

    def _increment_metric(self, name):
        with self._metrics_lock:
            self._metrics[name] += 1
