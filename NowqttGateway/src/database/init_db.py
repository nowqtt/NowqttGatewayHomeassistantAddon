import logging

import global_vars
from .db_migration import db_migration_0, db_migration_1


def insert_migration(migrations_id):
    with global_vars.sql_lite_connection:
        query = f"""
            INSERT INTO migration (id)
            VALUES (?)
        """

        global_vars.sql_lite_connection.execute(query, (migrations_id, ))


def create_tables():
    global_vars.sql_lite_connection.execute('''
        CREATE TABLE IF NOT EXISTS migration (
            id INTEGER PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute("SELECT id, timestamp FROM migration ORDER BY id DESC LIMIT 1;")
    migration_rows = cursor.fetchall()

    skip_migrations = -1
    if len(migration_rows) > 0:
        skip_migrations = migration_rows[0][0]

    migrations = [
        db_migration_0,
        db_migration_1
    ]

    for i in range(len(migrations)):
        if i <= skip_migrations:
            continue
        else:
            migrations[i]()
            insert_migration(i)

    logging.info("DB configured")
