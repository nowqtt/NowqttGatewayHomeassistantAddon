import json
import logging
import os
import re

from flask import Flask, jsonify, request, Response, render_template
from flasgger import Swagger
from werkzeug.serving import make_server

import global_vars

from .webserver_helper import (
    fetch_traces,
    fetch_devices,
    fetch_devices_names,
    patch_devices_names,
    delete_devices_names,
    fetch_devices_activity,
    trigger_ota_update,
    fetch_graph_data
)

app = Flask(__name__)
app.config['SWAGGER'] = {
    'openapi': '3.0.3'
}
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024 + 64 * 1024
SPEC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "spec", "swagger.yaml"))
swagger = Swagger(app, template_file=SPEC_PATH)

MAC_PATTERN = re.compile(r"^[0-9a-fA-F]{12}$")


def require_mac_address(mac_address):
    if not MAC_PATTERN.fullmatch(mac_address):
        raise ValueError("MAC address must contain exactly 12 hexadecimal digits")
    return mac_address.lower()


def require_query_integer(name, default, minimum=0, maximum=1000):
    raw_value = request.args.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as error:
        raise ValueError("%s must be an integer" % name) from error
    if value < minimum or value > maximum:
        raise ValueError("%s must be between %d and %d" % (name, minimum, maximum))
    return value


@app.errorhandler(ValueError)
def handle_bad_request(error):
    return jsonify(error=str(error)), 400


@app.errorhandler(RuntimeError)
def handle_conflict(error):
    return jsonify(error=str(error)), 409


@app.errorhandler(413)
def handle_upload_too_large(error):
    return jsonify(error="Firmware upload exceeds the configured size limit"), 413


@app.route("/v1/ota/update/<device_mac_address>", methods=['POST'])
def ota_update_device_mac_address(device_mac_address):
    device_mac_address = require_mac_address(device_mac_address)
    return jsonify(trigger_ota_update(device_mac_address, request.files)), 202


@app.route("/v1/ota/status", methods=['GET'])
def ota_status():
    return jsonify(global_vars.ota_coordinator.status())

@app.route("/v1/devices", methods=['GET'], endpoint='devices')
def devices():
    limit = require_query_integer("limit", 100, 1, 1000)
    offset = require_query_integer("offset", 0, 0, 1_000_000)
    return Response(response=fetch_devices(limit, offset),
                    status=200,
                    mimetype="application/json")

@app.route('/v1/devices/names', methods=['GET'])
def devices_names():
    limit = require_query_integer("limit", 100, 1, 1000)
    offset = require_query_integer("offset", 0, 0, 1_000_000)
    return Response(response=fetch_devices_names(None, limit, offset),
                    status=200,
                    mimetype="application/json")

@app.route('/v1/devices/<device_mac_address>/names', methods=['GET', 'PATCH', 'DELETE'])
def devices_device_mac_address_names(device_mac_address):
    device_mac_address = require_mac_address(device_mac_address)
    if request.method == 'GET':
        return Response(response=fetch_devices_names(device_mac_address, 1, 0),
                        status=200,
                        mimetype="application/json")

    elif request.method == 'PATCH':
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise ValueError("PATCH body must be a JSON object")
        name = body.get('name')
        if not isinstance(name, str) or not name.strip() or len(name) > 128:
            raise ValueError("Device name must contain between 1 and 128 characters")
        name = name.strip()

        patch_devices_names(device_mac_address, name)

        return Response(response=json.dumps({"name": name, "mac_address": device_mac_address}, indent=4),
                        status=201,
                        mimetype="application/json")

    elif request.method == 'DELETE':
        delete_devices_names(device_mac_address)

        return Response(status=204)

@app.route("/v1/traces", methods=['GET'], endpoint='traces')
def traces():
    device_mac_address = request.args.get('device_mac_address', default=None, type=str)
    if device_mac_address is not None:
        device_mac_address = require_mac_address(device_mac_address)
    last = require_query_integer("last", 100, 1, 1000)
    offset = require_query_integer("offset", 0, 0, 1_000_000)

    return Response(response=fetch_traces(device_mac_address, last, offset),
                    status=200,
                    mimetype="application/json")

@app.route("/v1/devices/activity", methods=['GET'])
def devices_activity():
    mac_address = request.args.get('device_mac_address', default=None, type=str)
    if mac_address is not None:
        mac_address = require_mac_address(mac_address)
    last = require_query_integer("last", 100, 1, 1000)
    offset = require_query_integer("offset", 0, 0, 1_000_000)

    return Response(response=fetch_devices_activity(mac_address, last, offset),
                    status=200,
                    mimetype="application/json")

@app.route("/", methods=['GET'])
def home():
    return render_template("index.html")

@app.route("/v1/graph/data", methods=['GET'])
def graph_data():
    return Response(response=fetch_graph_data(),
                    status=200,
                    mimetype="application/json")


@app.route("/v1/health", methods=['GET'])
def health():
    serial_metrics = global_vars.serial_task.snapshot_metrics()
    transport_metrics = global_vars.serial_transport.snapshot_metrics()
    runtime_workers = {
        worker.name: worker.status()
        for worker in getattr(global_vars, "background_workers", [])
    }
    mqtt_connected = global_vars.mqtt_gateway.is_connected()
    stopping = global_vars.stop_event.is_set()
    serial_workers_healthy = all(
        worker["alive"] and worker["failure"] is None
        for worker in serial_metrics["workers"].values()
    )
    runtime_workers_healthy = all(
        worker["alive"] and worker["failure"] is None
        for worker in runtime_workers.values()
    )
    healthy = all((
        transport_metrics["writer_healthy"],
        serial_metrics["running"],
        serial_workers_healthy,
        runtime_workers_healthy,
        mqtt_connected,
        not stopping,
    ))
    return jsonify({
        "healthy": healthy,
        "stopping": stopping,
        "mqtt_connected": mqtt_connected,
        "serial_reader": serial_metrics,
        "serial_writer": transport_metrics,
        "runtime_workers": runtime_workers,
        "ota": global_vars.ota_coordinator.status(),
    }), 200 if healthy else 503

@app.route("/graph", methods=['GET'])
def graph_page():
    return render_template("graph.html")

def run(stop_event):
    logging.info("Web server running on port 54321")
    server = make_server("0.0.0.0", 54321, app, threaded=True)
    server.timeout = 0.5
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        server.server_close()
