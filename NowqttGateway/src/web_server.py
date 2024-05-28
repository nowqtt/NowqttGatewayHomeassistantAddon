import logging
import os

from flask import Flask, request, Response
from flasgger import Swagger

import global_vars
from database import db_helper

app = Flask(__name__)
app.config['SWAGGER'] = {
    'openapi': '3.0.3'
}
swagger = Swagger(app, template_file=os.path.abspath('/app/spec/swagger.yaml'))

@app.route("/v1/devices", methods=['GET'], endpoint='devices')
def devices():
    return Response(response=db_helper.fetch_devices(),
                    status=200,
                    mimetype="application/json")

@app.route("/v1/traces", methods=['GET'], endpoint='traces')
def traces():
    device_mac_address = request.args.get('device_mac_address', default=None, type=str)
    last = request.args.get('last', default=None, type=str)

    return Response(response=db_helper.fetch_traces(device_mac_address, last),
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
    logging.info("Web server running on port %s", global_vars.config["web_server"]["port"])
    app.run(debug=True, use_reloader=False, host='0.0.0.0', port=global_vars.config["web_server"]["port"])