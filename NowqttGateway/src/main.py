import json
import logging

import global_vars
import serial

import yaml

from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

import serial_task


if __name__ == '__main__':
    global_vars.config = {}
    with open("config.yaml", "r") as user_file:
        try:
            temp = yaml.safe_load(user_file)
            global_vars.config = temp['config']
        except Exception as e:
            logging.error(e)

    logging.basicConfig(level=global_vars.config["log_level"])

    com_port = global_vars.config["serial"]["com_port"]
    baudrate = global_vars.config["serial"]["baudrate"]

    global_vars.mqtt_client_credentials = global_vars.config["mqtt_client"]

    global_vars.serial = serial.Serial(com_port, baudrate)

    influx_write_apis = {}

    if "influx" in global_vars.config:
        for i in global_vars.config.influx:
            url = i[list(i.keys())[0]]["url"]
            token = i[list(i.keys())[0]]["token"]
            org = list(i.keys())[0]

            influx_client = InfluxDBClient(url=url,
                                           token=token,
                                           org=org)
            influx_write_api = influx_client.write_api(write_options=SYNCHRONOUS)

            influx_write_apis[list(i.keys())[0]] = influx_write_api

    # Start serial_task
    serial_task.SerialTask(influx_write_apis).start_serial_task()
