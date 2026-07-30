import pathlib
import sqlite3
import sys
import tempfile
import unittest


SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from nowqtt_database import (
    count_activity,
    create_tables,
    find_device_names,
    find_with_filters,
    insert_devices_names,
    insert_device_activity_table,
    insert_trace_with_hops,
)


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = str(pathlib.Path(self.temp_dir.name) / "gateway.db")
        create_tables(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_migrations_are_repeatable(self):
        create_tables(self.database_path)
        with sqlite3.connect(self.database_path) as database:
            migrations = database.execute("SELECT id FROM migration ORDER BY id").fetchall()
        self.assertEqual(migrations, [(0,), (1,), (2,), (3,), (4,), (5,)])

    def test_trace_and_all_hops_are_stored_together(self):
        hops = [{
            "hop_counter": 0,
            "hop_mac_address": "001122334455",
            "hop_rssi": -62,
            "hop_dest_seq": 42,
            "route_age": 1,
            "hop_count": 2,
        }]
        self.assertTrue(insert_trace_with_hops("aabbccddeeff", "trace-1", hops))
        rows = find_with_filters("aabbccddeeff", 10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][4], "001122334455")
        self.assertEqual(rows[0][5], -62)

    def test_device_names_are_parameterized(self):
        unsafe_name = "Kitchen'); DROP TABLE trace; --"
        insert_devices_names("aabbccddeeff", unsafe_name, 1)
        self.assertEqual(find_device_names("aabbccddeeff")[0][0], unsafe_name)
        with sqlite3.connect(self.database_path) as database:
            database.execute("SELECT COUNT(*) FROM trace").fetchone()

    def test_device_names_and_activity_are_bounded(self):
        for index in range(5):
            mac_address = "%012x" % index
            insert_devices_names(mac_address, "Device %d" % index, 1)
            insert_device_activity_table(mac_address, 1)

        self.assertEqual(len(find_device_names(None, limit=2)), 2)
        self.assertEqual(len(find_device_names(None, limit=2, offset=2)), 2)
        self.assertEqual(count_activity(activity=1), 5)

    def test_every_connection_uses_normal_synchronous_mode(self):
        with sqlite3.connect(self.database_path) as database:
            database.execute("PRAGMA synchronous=NORMAL")
            expected = database.execute("PRAGMA synchronous").fetchone()[0]
        from nowqtt_database.database import connection
        with connection() as database:
            self.assertEqual(database.execute("PRAGMA synchronous").fetchone()[0], expected)


if __name__ == "__main__":
    unittest.main()
