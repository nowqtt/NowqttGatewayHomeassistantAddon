import logging
import os

from flask import Flask, request
from flasgger import Swagger

import global_vars
import db_helper

app = Flask(__name__)
app.config['SWAGGER'] = {
    'openapi': '3.0.3'
}
swagger = Swagger(app, template_file=os.path.abspath('/app/spec/swagger.yaml'))

@app.route("/v1/devices", methods=['GET'], endpoint='devices')
def devices():
    return db_helper.fetch_devices()

@app.route("/v1/traces", methods=['GET'], endpoint='traces')
def traces():
    device_mac_address = request.args.get('device_mac_address', default=None, type=str)
    last = request.args.get('last', default=None, type=str)

    return db_helper.fetch_traces(device_mac_address, last)

def run():
    logging.info("Web server running on port %s", global_vars.config["web_server"]["port"])
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=global_vars.config["web_server"]["port"])