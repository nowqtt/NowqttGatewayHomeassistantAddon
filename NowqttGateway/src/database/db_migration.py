import global_vars

def db_migration_0():
    with global_vars.sql_lite_connection:
        global_vars.sql_lite_connection.execute('''
            CREATE TABLE trace (
                uuid TEXT PRIMARY KEY,
                dest_mac_address TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        global_vars.sql_lite_connection.execute('''
            CREATE TABLE hop (
                trace_uuid TEXT,
                hop_counter INTEGER NOT NULL,
                hop_mac_address TEXT NOT NULL,
                hop_rssi INTEGER NOT NULL,
                PRIMARY KEY (trace_uuid, hop_counter),
                FOREIGN KEY (trace_uuid) REFERENCES trace (uuid)
            )
        ''')

        global_vars.sql_lite_connection.execute('''
            CREATE TABLE device_names (
                mac_address TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        ''')

        global_vars.sql_lite_connection.execute('''
            CREATE TABLE device_activity (
                mac_address TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                activity INTEGER,
                PRIMARY KEY (mac_address, timestamp)
            )
        ''')

        global_vars.sql_lite_connection.execute(
            'CREATE INDEX dest_mac_address_index ON trace(dest_mac_address);'
        )

        global_vars.sql_lite_connection.execute(
            'CREATE INDEX timestamp_index ON trace(timestamp);'
        )

        global_vars.sql_lite_connection.execute(
            'CREATE INDEX trace_uuid_index ON hop(trace_uuid);'
        )


def db_migration_1():
    global_vars.sql_lite_connection.execute('''
        ALTER TABLE trace ADD COLUMN hop_dest_seq INTEGER NOT NULL;
        ALTER TABLE trace ADD COLUMN hop_age INTEGER NOT NULL;
        ALTER TABLE trace ADD COLUMN hop_count INTEGER NOT NULL;
    ''')
