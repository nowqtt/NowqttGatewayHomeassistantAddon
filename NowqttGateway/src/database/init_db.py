import logging

import global_vars

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

        global_vars.sql_lite_connection.execute('''
            CREATE TABLE IF NOT EXISTS device_names (
                mac_address TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        ''')

        global_vars.sql_lite_connection.execute(
            'CREATE INDEX IF NOT EXISTS dest_mac_address_index ON trace(dest_mac_address);'
        )

        global_vars.sql_lite_connection.execute(
            'CREATE INDEX IF NOT EXISTS timestamp_index ON trace(timestamp);'
        )

        global_vars.sql_lite_connection.execute(
            'CREATE INDEX IF NOT EXISTS trace_uuid_index ON hop(trace_uuid);'
        )

        logging.info("DB configured")