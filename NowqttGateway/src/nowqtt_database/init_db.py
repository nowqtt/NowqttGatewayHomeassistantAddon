import logging

from .database import configure_database, connection
from .db_migration import (
    db_migration_0,
    db_migration_1,
    db_migration_2,
    db_migration_3,
    db_migration_4,
    db_migration_5,
)


def create_tables(database_path=None):
    if database_path is not None:
        configure_database(database_path)

    with connection() as database:
        database.execute('''
            CREATE TABLE IF NOT EXISTS migration (
                id INTEGER PRIMARY KEY,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        row = database.execute("SELECT MAX(id) FROM migration").fetchone()
        last_migration = row[0] if row and row[0] is not None else -1

        migrations = [
            db_migration_0,
            db_migration_1,
            db_migration_2,
            db_migration_3,
            db_migration_4,
            db_migration_5,
        ]
        for migration_id, migration in enumerate(migrations):
            if migration_id <= last_migration:
                continue
            migration(database)
            database.execute("INSERT INTO migration (id) VALUES (?)", (migration_id,))

    logging.info("DB configured")
