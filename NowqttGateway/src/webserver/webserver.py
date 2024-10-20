import json
import logging
import os

from flask import Flask, request, Response
from flasgger import Swagger

import global_vars

from .webserver_helper import (
    fetch_traces,
    fetch_devices,
    fetch_devices_names,
    patch_devices_names,
    delete_devices_names,
    fetch_devices_activity,
    trigger_ota_update
)

app = Flask(__name__)
app.config['SWAGGER'] = {
    'openapi': '3.0.3'
}
swagger = Swagger(app, template_file=os.path.abspath('/app/spec/swagger.yaml'))

#TODO callback when ota is finished would be nice
@app.route("/v1/ota/update/<device_mac_address>", methods=['POST'])
def ota_update_device_mac_address(device_mac_address):
    return Response(response=trigger_ota_update(device_mac_address, request.files),
                    status=200,
                    mimetype="application/json")

@app.route("/v1/devices", methods=['GET'], endpoint='devices')
def devices():
    return Response(response=fetch_devices(),
                    status=200,
                    mimetype="application/json")

@app.route('/v1/devices/names', methods=['GET'])
def devices_names():
    return Response(response=fetch_devices_names(),
                    status=200,
                    mimetype="application/json")

@app.route('/v1/devices/<device_mac_address>/names', methods=['GET', 'PATCH', 'DELETE'])
def devices_device_mac_address_names(device_mac_address):
    if request.method == 'GET':
        return Response(response=fetch_devices_names(device_mac_address),
                        status=200,
                        mimetype="application/json")

    elif request.method == 'PATCH':
        name = request.get_json().get('name')

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
    last = request.args.get('last', default="100", type=str)

    return Response(response=fetch_traces(device_mac_address, last),
                    status=200,
                    mimetype="application/json")

@app.route("/v1/devices/activity", methods=['GET'])
def devices_activity():
    mac_address = request.args.get('device_mac_address', default=None, type=str)
    last = request.args.get('last', default=100, type=int)

    return Response(response=fetch_devices_activity(mac_address, last),
                    status=200,
                    mimetype="application/json")

@app.route("/", methods=['GET'])
def home():
    response_body = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Welcome to the API</title>
        </head>
        <body>
            <h1>Welcome to the Nowqtt Gateway</h1>
            <p>You can find the API documentation <a href="/apidocs">here</a>.</p>
        </body>
        </html>
    """

    return Response(response=response_body,
                        status=200,
                        mimetype="text/html")

def run():
    logging.info("Web server running on port 54321")
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=1234)