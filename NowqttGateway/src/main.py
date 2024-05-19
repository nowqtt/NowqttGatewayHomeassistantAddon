import json
import logging
import sqlite3
import threading

import global_vars
import serial

import yaml

import serial_task
import web_server

def create_tables():
    with global_vars.sql_lite_connection:
        global_vars.sql_lite_connection.execute('''
            CREATE TABLE IF NOT EXISTS trace (
                uuid TEXT PRIMARY KEY,
                dest_mac_address TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        global_vars.sql_lite_connection.execute('''
            CREATE TABLE IF NOT EXISTS hop (
                trace_uuid TEXT,
                hop_counter INTEGER NOT NULL,
                hop_mac_address TEXT NOT NULL,
                hop_rssi INTEGER NOT NULL,
                PRIMARY KEY (trace_uuid, hop_counter),
                FOREIGN KEY (trace_uuid) REFERENCES trace (uuid)
            )
        ''')

        logging.info("")

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

    flask_thread = threading.Thread(target=web_server.run)
    flask_thread.start()

    com_port = global_vars.config["serial"]["com_port"]
    baudrate = global_vars.config["serial"]["baudrate"]

    global_vars.mqtt_client_credentials = global_vars.config["mqtt_client"]

    global_vars.serial = serial.Serial(com_port, baudrate)

    # Start serial_task
    serial_task.SerialTask().start_serial_task()
