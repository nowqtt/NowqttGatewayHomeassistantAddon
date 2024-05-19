import logging

from flask import Flask, request

import global_vars
import db_helper

app = Flask(__name__)

@app.route("/devices", methods=['GET'], endpoint='devices')
def devices():
    return db_helper.fetch_devices()

@app.route("/traces", methods=['GET'], endpoint='traces')
def traces():
    device_mac_address = request.args.get('device_mac_address', default=None, type=str)
    last = request.args.get('last', default=None, type=str)

    return db_helper.fetch_traces(device_mac_address, last)

def run():
    logging.info("Web server running on port %i", global_vars.config["web_server"]["port"])
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=global_vars.config["web_server"]["port"])