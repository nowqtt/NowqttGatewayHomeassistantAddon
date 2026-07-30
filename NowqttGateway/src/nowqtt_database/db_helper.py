import logging
import threading

from .database import connection


MAX_QUERY_ROWS = 1000
_graph_revision = 0
_graph_revision_lock = threading.Lock()


def _bounded_limit(limit, default=100):
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, MAX_QUERY_ROWS))


def _bounded_offset(offset):
    try:
        parsed = int(offset)
    except (TypeError, ValueError):
        parsed = 0
    return max(0, min(parsed, 1_000_000))


def _mark_graph_changed():
    global _graph_revision
    with _graph_revision_lock:
        _graph_revision += 1


def get_graph_revision():
    with _graph_revision_lock:
        return _graph_revision


def find_with_filters(device_mac_address=None, last=100, offset=0):
    trace_filter = "" if device_mac_address is None else "WHERE dest_mac_address = ?"
    query = '''
        SELECT
            trace.uuid,
            trace.dest_mac_address,
            trace.timestamp,
            hop.hop_counter,
            hop.hop_mac_address,
            hop.hop_rssi,
            device_names.name,
            hop.hop_dest_seq,
            hop.route_age,
            hop.hop_count
        FROM trace
        LEFT JOIN hop ON trace.uuid = hop.trace_uuid
        LEFT JOIN device_names ON hop.hop_mac_address = device_names.mac_address
        WHERE trace.uuid IN (
            SELECT uuid FROM trace
            {trace_filter}
            ORDER BY timestamp DESC, rowid DESC
            LIMIT ? OFFSET ?
        )
        ORDER BY trace.timestamp DESC, hop.hop_counter ASC
    '''.format(trace_filter=trace_filter)
    parameters = [] if device_mac_address is None else [device_mac_address]
    parameters.extend((_bounded_limit(last), _bounded_offset(offset)))
    with connection() as database:
        return database.execute(query, parameters).fetchall()


def count_traces(device_mac_address=None):
    with connection() as database:
        if device_mac_address is None:
            return database.execute("SELECT COUNT(*) FROM trace").fetchone()[0]
        return database.execute(
            "SELECT COUNT(*) FROM trace WHERE dest_mac_address = ?",
            (device_mac_address,),
        ).fetchone()[0]


def find_devices(limit=100, offset=0):
    query = '''
        SELECT DISTINCT trace.dest_mac_address, device_names.name
        FROM trace
        LEFT JOIN device_names ON trace.dest_mac_address = device_names.mac_address
        ORDER BY trace.dest_mac_address ASC
        LIMIT ? OFFSET ?
    '''
    with connection() as database:
        return database.execute(
            query, (_bounded_limit(limit), _bounded_offset(offset))
        ).fetchall()


def count_devices():
    with connection() as database:
        return database.execute(
            "SELECT COUNT(DISTINCT dest_mac_address) FROM trace"
        ).fetchone()[0]


def find_device_names(mac_address=None, limit=100, offset=0):
    name_filter = "" if mac_address is None else "WHERE mac_address = ?"
    query = '''
        SELECT name, mac_address, manual_input
        FROM device_names
        {name_filter}
        ORDER BY mac_address ASC
        LIMIT ? OFFSET ?
    '''.format(name_filter=name_filter)
    parameters = [] if mac_address is None else [mac_address]
    parameters.extend((_bounded_limit(limit), _bounded_offset(offset)))
    with connection() as database:
        return database.execute(query, parameters).fetchall()


def count_device_names(mac_address=None):
    with connection() as database:
        if mac_address is None:
            return database.execute("SELECT COUNT(*) FROM device_names").fetchone()[0]
        return database.execute(
            "SELECT COUNT(*) FROM device_names WHERE mac_address = ?",
            (mac_address,),
        ).fetchone()[0]


def update_devices_names(mac_address, name, manual_input):
    try:
        with connection() as database:
            database.execute(
                "UPDATE device_names SET name = ?, manual_input = ? WHERE mac_address = ?",
                (name, manual_input, mac_address),
            )
        _mark_graph_changed()
    except Exception:
        logging.exception("DB device-name update failed")


def insert_devices_names(mac_address, name, manual_input):
    try:
        with connection() as database:
            database.execute(
                "INSERT INTO device_names (name, mac_address, manual_input) VALUES (?, ?, ?)",
                (name, mac_address, manual_input),
            )
        _mark_graph_changed()
    except Exception:
        logging.exception("DB device-name insert failed")


def remove_devices_names(mac_address):
    try:
        with connection() as database:
            database.execute("DELETE FROM device_names WHERE mac_address = ?", (mac_address,))
        _mark_graph_changed()
    except Exception:
        logging.exception("DB device-name delete failed")


def insert_trace_with_hops(dest_mac_address, trace_uuid, hops):
    try:
        with connection() as database:
            database.execute(
                "INSERT INTO trace (uuid, dest_mac_address) VALUES (?, ?)",
                (trace_uuid, dest_mac_address),
            )
            database.executemany(
                '''
                    INSERT INTO hop (
                        trace_uuid, hop_counter, hop_mac_address, hop_rssi,
                        hop_dest_seq, route_age, hop_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                [
                    (
                        trace_uuid,
                        hop["hop_counter"],
                        hop["hop_mac_address"],
                        hop["hop_rssi"],
                        hop["hop_dest_seq"],
                        hop["route_age"],
                        hop["hop_count"],
                    )
                    for hop in hops
                ],
            )
        _mark_graph_changed()
        return True
    except Exception:
        logging.exception("DB trace insert failed")
        return False


def insert_trace_table(dest_mac_address, trace_uuid):
    return insert_trace_with_hops(dest_mac_address, trace_uuid, [])


def insert_hop_table(trace_uuid, hop_counter, hop_mac_address, hop_rssi,
                     hop_dest_seq, route_age, hop_count):
    try:
        with connection() as database:
            database.execute(
                '''
                    INSERT INTO hop (
                        trace_uuid, hop_counter, hop_mac_address, hop_rssi,
                        hop_dest_seq, route_age, hop_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    trace_uuid, hop_counter, hop_mac_address, hop_rssi,
                    hop_dest_seq, route_age, hop_count,
                ),
            )
        return True
    except Exception:
        logging.exception("DB hop insert failed")
        return False


def insert_device_activity_table(mac_address, activity):
    try:
        with connection() as database:
            database.execute(
                "INSERT INTO device_activity (mac_address, activity) VALUES (?, ?)",
                (mac_address, activity),
            )
        return True
    except Exception:
        logging.exception("DB activity insert failed")
        return False


def find_current_activity_data(limit=100, offset=0):
    query = '''
        WITH latest AS (
            SELECT mac_address, MAX(rowid) AS latest_rowid
            FROM device_activity
            GROUP BY mac_address
        )
        SELECT activity.mac_address, activity.timestamp, activity.activity, device_names.name
        FROM latest
        JOIN device_activity AS activity ON activity.rowid = latest.latest_rowid
        LEFT JOIN device_names ON activity.mac_address = device_names.mac_address
        ORDER BY activity.mac_address ASC
        LIMIT ? OFFSET ?
    '''
    with connection() as database:
        return database.execute(
            query, (_bounded_limit(limit), _bounded_offset(offset))
        ).fetchall()


def find_activity_by_mac_address(mac_address, limit, offset=0):
    query = '''
        SELECT activity.mac_address, activity.timestamp, activity.activity, device_names.name
        FROM device_activity AS activity
        LEFT JOIN device_names ON activity.mac_address = device_names.mac_address
        WHERE activity.mac_address = ?
        ORDER BY activity.timestamp DESC, activity.rowid DESC
        LIMIT ? OFFSET ?
    '''
    with connection() as database:
        return database.execute(
            query, (mac_address, _bounded_limit(limit), _bounded_offset(offset))
        ).fetchall()


def count_activity(mac_address=None, activity=None):
    if mac_address is not None:
        with connection() as database:
            return database.execute(
                "SELECT COUNT(*) FROM device_activity WHERE mac_address = ?",
                (mac_address,),
            ).fetchone()[0]

    query = '''
        WITH latest AS (
            SELECT mac_address, MAX(rowid) AS latest_rowid
            FROM device_activity
            GROUP BY mac_address
        )
        SELECT COUNT(*)
        FROM latest
        JOIN device_activity AS current ON current.rowid = latest.latest_rowid
        AND (? IS NULL OR current.activity = ?)
    '''
    with connection() as database:
        return database.execute(query, (activity, activity)).fetchone()[0]


def count_current_activity_states():
    query = '''
        WITH latest AS (
            SELECT mac_address, MAX(rowid) AS latest_rowid
            FROM device_activity
            GROUP BY mac_address
        )
        SELECT
            COUNT(*),
            COALESCE(SUM(current.activity = 1), 0),
            COALESCE(SUM(current.activity = 0), 0)
        FROM latest
        JOIN device_activity AS current ON current.rowid = latest.latest_rowid
    '''
    with connection() as database:
        return database.execute(query).fetchone()


def find_last_trace_of_each_device(max_age_seconds=180, limit=1000):
    try:
        max_age_seconds = int(max_age_seconds)
    except (TypeError, ValueError):
        max_age_seconds = 180
    max_age_seconds = max(1, min(max_age_seconds, 7 * 24 * 60 * 60))
    modifier = "-%d seconds" % max_age_seconds
    query = '''
        WITH ranked AS (
            SELECT
                trace.uuid,
                trace.dest_mac_address,
                trace.timestamp,
                ROW_NUMBER() OVER (
                    PARTITION BY trace.dest_mac_address
                    ORDER BY trace.timestamp DESC, trace.rowid DESC
                ) AS row_number
            FROM trace
            WHERE trace.timestamp > datetime('now', ?)
        ), latest AS (
            SELECT uuid, dest_mac_address, timestamp
            FROM ranked
            WHERE row_number = 1
            ORDER BY dest_mac_address ASC
            LIMIT ?
        )
        SELECT latest.uuid, latest.timestamp, hop.hop_mac_address,
               hop.hop_rssi, hop.hop_counter
        FROM latest
        LEFT JOIN hop ON latest.uuid = hop.trace_uuid
        ORDER BY latest.uuid ASC, hop.hop_counter ASC
    '''
    with connection() as database:
        return database.execute(
            query, (modifier, _bounded_limit(limit, default=1000))
        ).fetchall()


def prune_trace_history(retention_days):
    retention_days = max(1, int(retention_days))
    modifier = "-%d days" % retention_days
    with connection() as database:
        database.execute(
            "DELETE FROM hop WHERE trace_uuid IN "
            "(SELECT uuid FROM trace WHERE timestamp < datetime('now', ?))",
            (modifier,),
        )
        cursor = database.execute(
            "DELETE FROM trace WHERE timestamp < datetime('now', ?)",
            (modifier,),
        )
        return cursor.rowcount
