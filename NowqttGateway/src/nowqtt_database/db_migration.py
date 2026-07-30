def db_migration_0(database):
        database.execute('''
            CREATE TABLE trace (
                uuid TEXT PRIMARY KEY,
                dest_mac_address TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        database.execute('''
            CREATE TABLE hop (
                trace_uuid TEXT,
                hop_counter INTEGER NOT NULL,
                hop_mac_address TEXT NOT NULL,
                hop_rssi INTEGER NOT NULL,
                PRIMARY KEY (trace_uuid, hop_counter),
                FOREIGN KEY (trace_uuid) REFERENCES trace (uuid)
            )
        ''')

        database.execute('''
            CREATE TABLE device_names (
                mac_address TEXT PRIMARY KEY,
                name TEXT NOT NULL
            )
        ''')

        database.execute('''
            CREATE TABLE device_activity (
                mac_address TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                activity INTEGER,
                PRIMARY KEY (mac_address, timestamp)
            )
        ''')

        database.execute(
            'CREATE INDEX dest_mac_address_index ON trace(dest_mac_address);'
        )

        database.execute(
            'CREATE INDEX timestamp_index ON trace(timestamp);'
        )

        database.execute(
            'CREATE INDEX trace_uuid_index ON hop(trace_uuid);'
        )


def db_migration_1(database):
        database.execute('''
            ALTER TABLE hop ADD COLUMN hop_dest_seq INTEGER NOT NULL;
        ''')
        database.execute('''
            ALTER TABLE hop ADD COLUMN hop_age INTEGER NOT NULL;
        ''')
        database.execute('''
            ALTER TABLE hop ADD COLUMN hop_count INTEGER NOT NULL;
        ''')

def db_migration_2(database):
        database.execute('''
            ALTER TABLE hop RENAME COLUMN hop_age TO route_age;
        ''')

def db_migration_3(database):
        database.execute('''
            ALTER TABLE device_names ADD COLUMN manual_input INTEGER NOT NULL DEFAULT 0;
        ''')

def db_migration_4(database):
    database.execute('''
        CREATE INDEX IF NOT EXISTS activity_mac_timestamp_index
        ON device_activity(mac_address, timestamp DESC);
    ''')


def db_migration_5(database):
    database.execute('''
        CREATE INDEX IF NOT EXISTS trace_mac_timestamp_index
        ON trace(dest_mac_address, timestamp DESC);
    ''')
