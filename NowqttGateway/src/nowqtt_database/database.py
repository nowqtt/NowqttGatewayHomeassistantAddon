import os
import sqlite3
import threading
from contextlib import contextmanager


_database_path = "/data/sql_lite_database.db"
_path_lock = threading.Lock()


def configure_database(database_path):
    global _database_path
    with _path_lock:
        _database_path = database_path

    parent_directory = os.path.dirname(os.path.abspath(database_path))
    if parent_directory:
        os.makedirs(parent_directory, exist_ok=True)

    with connection() as database:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA synchronous=NORMAL")


@contextmanager
def connection():
    with _path_lock:
        database_path = _database_path

    database = sqlite3.connect(database_path, timeout=5)
    database.execute("PRAGMA busy_timeout=5000")
    database.execute("PRAGMA foreign_keys=ON")
    database.execute("PRAGMA synchronous=NORMAL")
    try:
        yield database
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()
