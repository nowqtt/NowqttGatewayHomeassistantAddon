import logging

import global_vars

def find_qb():
    return """
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
    """

def find_trace_qb():
    return """
        SELECT
            trace.uuid, 
            trace.dest_mac_address, 
            trace.timestamp
        FROM trace
    """

def find_device_names_qb():
    return """
        SELECT
            device_names.name, 
            device_names.mac_address,
            device_names.manual_input
        FROM device_names
    """

def handle_filters(filters):
    query = ""
    counter = 0
    for f in filters:
        if counter == 0:
            query += " WHERE " + f
        else:
            query += " AND  " + f

        counter += 1

    return query

def find_trace_with_filters(filters, last):
    query = find_trace_qb()
    query += handle_filters(filters)
    query += " ORDER BY trace.timestamp DESC"

    if last is not None:
        query += " LIMIT " + last

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)
    return cursor.fetchall()

def find_with_filters(filters, last):
    query = find_qb()
    query += handle_filters(filters)

    if last is not None:
        traces = find_trace_with_filters(filters, last)

        traces_to_find = "("
        counter = 0
        for trace in traces:
            if counter != 0:
                traces_to_find += ","
            traces_to_find += "'" + trace[0] + "'"

            counter += 1

        traces_to_find += ")"

        if len(filters) > 0:
            query += " AND "
        else :
            query += " WHERE "

        query += " trace.uuid IN " + traces_to_find

    query += " ORDER BY trace.timestamp DESC"

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)
    return cursor.fetchall()

def find_devices():
    query = """
        SELECT DISTINCT
            trace.dest_mac_address,
            device_names.name
        FROM trace
        LEFT JOIN device_names ON trace.dest_mac_address = device_names.mac_address
    """

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)
    return cursor.fetchall()

def find_device_names(mac_address):
    query = find_device_names_qb()
    if mac_address is not None:
        query += f" WHERE device_names.mac_address LIKE '{mac_address}'"

    query += "ORDER BY device_names.mac_address asc"

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)
    return cursor.fetchall()

def update_devices_names(mac_address, name, manual_input):
    try:
        query = f"""
            UPDATE device_names
            SET name = '{name}', manual_input = {manual_input}
            WHERE device_names.mac_address like '{mac_address}'
        """

        cursor = global_vars.sql_lite_connection.cursor()
        cursor.execute(query)
    except Exception as e:
        logging.error(f"An error occurred during DB update: {e}")

def insert_devices_names(mac_address, name, manual_input):
    try:
        query = f"""
            INSERT INTO device_names (name, mac_address, manual_input)
            VALUES ('{name}', '{mac_address}', {manual_input})
        """

        cursor = global_vars.sql_lite_connection.cursor()
        cursor.execute(query)
    except Exception as e:
        logging.error(f"An error occurred during DB insert: {e}")

def remove_devices_names(mac_address):
    try:
        query = f"""
            DELETE FROM  device_names
            WHERE mac_address like '{mac_address}'
        """

        cursor = global_vars.sql_lite_connection.cursor()
        cursor.execute(query)
    except Exception as e:
        logging.error(f"An error occurred during DB delete: {e}")

def insert_trace_table(dest_mac_address, trace_uuid):
    try:
        with global_vars.sql_lite_connection:
            global_vars.sql_lite_connection.execute(
                "INSERT INTO trace (uuid, dest_mac_address) VALUES (?, ?)",
                (trace_uuid, dest_mac_address)
            )
    except Exception as e:
        logging.error(f"An error occurred during DB insert: {e}")

def insert_hop_table(trace_uuid, hop_counter, hop_mac_address, hop_rssi, hop_dest_seq, route_age, hop_count):
    try:
        with global_vars.sql_lite_connection:
            query = f"""
                INSERT INTO hop
                (trace_uuid, hop_counter, hop_mac_address, hop_rssi, hop_dest_seq, route_age, hop_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            global_vars.sql_lite_connection.execute(query,
                (trace_uuid, hop_counter, hop_mac_address, hop_rssi, hop_dest_seq, route_age, hop_count)
            )
    except Exception as e:
        logging.error(f"An error occurred during DB insert: {e}")

def insert_device_activity_table(mac_address, activity):
    try:
        with global_vars.sql_lite_connection:
            global_vars.sql_lite_connection.execute(
                "INSERT INTO device_activity (mac_address, activity) VALUES (?, ?)",
                (mac_address, activity)
            )
    except Exception as e:
        logging.error(f"An error occurred during DB insert: {e}")

def find_current_activity_data():
    query = f"""
        SELECT device_activity.mac_address, MAX(timestamp) AS last_timestamp, activity, device_names.name
        FROM device_activity
        INNER JOIN device_names ON device_activity.mac_address = device_names.mac_address
        GROUP BY device_activity.mac_address
    """

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)
    return cursor.fetchall()

def find_activity_by_mac_address(mac_address, limit):
    query = f"""
            SELECT device_activity.mac_address, timestamp, activity, device_names.name
            FROM device_activity
            LEFT JOIN device_names ON device_activity.mac_address = device_names.mac_address
            WHERE device_activity.mac_address like '{mac_address}'
            ORDER BY device_activity.timestamp
            LIMIT {limit}
        """

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)
    return cursor.fetchall()

def find_active_or_inactive_devices(activity):
    query = f"""
        SELECT device_activity.mac_address, MAX(timestamp) AS last_timestamp, activity, device_names.name
        FROM device_activity
        INNER JOIN device_names ON device_activity.mac_address = device_names.mac_address
        GROUP BY device_activity.mac_address
    """

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)
    activities = cursor.fetchall()

    result = []
    for a in activities:
        if a[2] == activity:
            result.append(a)

    return result
