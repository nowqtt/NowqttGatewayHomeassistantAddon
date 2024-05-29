import logging
import sqlite3
import threading

import global_vars
import serial

import yaml

from gateway import SerialTask
from webserver import webserver
from database import create_tables

if __name__ == '__main__':
    global_vars.config = {}
    with open("config.yaml", "r") as user_file:
        try:
            temp = yaml.safe_load(user_file)
            global_vars.config = temp['config']
        except Exception as e:
            logging.error(e)

    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s %(message)s',
        level=global_vars.config["log_level"],
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    global_vars.sql_lite_connection = sqlite3.connect('/app/database/sql_lite_database.db', check_same_thread=False)

    create_tables()

    threading.Thread(target=webserver.run).start()

    com_port = global_vars.config["serial"]["com_port"]
    baudrate = global_vars.config["serial"]["baudrate"]

    global_vars.mqtt_client_credentials = global_vars.config["mqtt_client"]

    global_vars.serial = serial.Serial(com_port, baudrate)

    # Start serial_task
    SerialTask().start_serial_task()
