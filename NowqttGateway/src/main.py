import logging
import os
import signal
import sqlite3
import threading

import serial

import global_vars
from configuration import load_config
from gateway.mqtt_task import MQTTGateway
from gateway.managed_worker import ManagedWorker
from gateway.serial_task import SerialTask
from gateway.serial_transport import SerialTransport
from nowqtt_database import create_tables, prune_trace_history
from ota import OtaCoordinator
from webserver import webserver


OPTIONS_PATH = os.environ.get("NOWQTT_OPTIONS_PATH", "/data/options.json")
DATABASE_PATH = os.environ.get(
    "NOWQTT_DATABASE_PATH", "/data/sql_lite_database.db"
)
LEGACY_DATABASE_PATH = "/app/database/sql_lite_database.db"
_shutdown_lock = threading.Lock()
_shutdown_complete = False


def prune_history_task(stop_event):
    while not stop_event.is_set():
        try:
            deleted = prune_trace_history(global_vars.config["trace_retention_days"])
            if deleted:
                logging.info("Pruned %d old traces", deleted)
        except Exception:
            logging.exception("Trace retention task failed")
        stop_event.wait(24 * 60 * 60)


def shutdown():
    global _shutdown_complete
    with _shutdown_lock:
        if _shutdown_complete:
            return
        _shutdown_complete = True

    stop_event = getattr(global_vars, "stop_event", None)
    if stop_event is not None:
        stop_event.set()

    cleanup_steps = []
    coordinator = getattr(global_vars, "ota_coordinator", None)
    if coordinator is not None:
        cleanup_steps.append(("OTA coordinator", coordinator.cancel_and_wait))
    serial_task = getattr(global_vars, "serial_task", None)
    if serial_task is not None:
        cleanup_steps.append(("serial task", serial_task.close))
    cleanup_steps.extend(
        ("worker %s" % worker.name, lambda worker=worker: worker.join(timeout=2))
        for worker in getattr(global_vars, "background_workers", [])
    )
    mqtt_gateway = getattr(global_vars, "mqtt_gateway", None)
    if mqtt_gateway is not None:
        cleanup_steps.append(("MQTT gateway", mqtt_gateway.stop))
    serial_transport = getattr(global_vars, "serial_transport", None)
    if serial_transport is not None:
        cleanup_steps.append(("serial transport", serial_transport.close))
    serial_port = getattr(global_vars, "serial", None)
    if serial_port is not None:
        cleanup_steps.append((
            "serial port",
            lambda: serial_port.close() if serial_port.is_open else None,
        ))

    for name, cleanup in cleanup_steps:
        try:
            cleanup()
        except Exception:
            logging.exception("Failed to stop %s", name)


def _migrate_legacy_database():
    if DATABASE_PATH == LEGACY_DATABASE_PATH or os.path.exists(DATABASE_PATH):
        return
    if not os.path.exists(LEGACY_DATABASE_PATH):
        return
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    with sqlite3.connect(LEGACY_DATABASE_PATH) as source:
        with sqlite3.connect(DATABASE_PATH) as destination:
            source.backup(destination)
    logging.info("Migrated legacy database to %s", DATABASE_PATH)


def _worker_failure():
    serial_task = getattr(global_vars, "serial_task", None)
    if serial_task is not None and serial_task.failure() is not None:
        return serial_task.failure()
    for worker in getattr(global_vars, "background_workers", []):
        if worker.failure() is not None:
            return "%s: %s" % (worker.name, worker.failure())
    return None


def main():
    global _shutdown_complete
    _shutdown_complete = False
    global_vars.stop_event = threading.Event()
    global_vars.background_workers = []
    try:
        global_vars.config = load_config(OPTIONS_PATH)
        logging.basicConfig(
            format="%(asctime)s %(levelname)-8s %(message)s",
            level=global_vars.config["log_level"],
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        webserver.app.config["MAX_CONTENT_LENGTH"] = (
            global_vars.config["max_ota_firmware_size"] + 64 * 1024
        )

        _migrate_legacy_database()
        create_tables(DATABASE_PATH)
        global_vars.mqtt_client_credentials = global_vars.config["mqtt_client"]
        global_vars.ota_coordinator = OtaCoordinator(
            max_firmware_size=global_vars.config["max_ota_firmware_size"],
            session_timeout=global_vars.config["ota_session_timeout_seconds"],
        )

        serial_config = global_vars.config["serial"]
        global_vars.serial = serial.Serial(
            serial_config["com_port"],
            serial_config["baudrate"],
            timeout=global_vars.config["serial_read_timeout_seconds"],
            write_timeout=global_vars.config["serial_write_timeout_seconds"],
        )
        global_vars.serial_transport = SerialTransport(
            global_vars.serial,
            queue_size=global_vars.config["serial_output_queue_size"],
        )
        global_vars.serial_transport.start()

        global_vars.mqtt_gateway = MQTTGateway()
        global_vars.mqtt_gateway.start()

        serial_task = SerialTask(global_vars.mqtt_gateway, global_vars.stop_event)
        global_vars.serial_task = serial_task

        def request_shutdown(signum, frame):
            logging.info("Received signal %d; stopping gateway", signum)
            global_vars.stop_event.set()

        signal.signal(signal.SIGTERM, request_shutdown)
        signal.signal(signal.SIGINT, request_shutdown)
        global_vars.background_workers = [
            ManagedWorker("webserver", webserver.run, global_vars.stop_event),
            ManagedWorker("trace-retention", prune_history_task, global_vars.stop_event),
        ]

        for worker in global_vars.background_workers:
            worker.start()
        serial_task.start_serial_task()
        failure = _worker_failure()
        if failure is not None:
            raise RuntimeError("Required worker failed: %s" % failure)
    finally:
        shutdown()


if __name__ == "__main__":
    main()
