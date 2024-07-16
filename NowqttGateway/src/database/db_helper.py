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
            device_names.name
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
            device_names.mac_address
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

def find_all():
    query = find_qb()
    query += " ORDER BY trace.timestamp DESC"

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)
    return cursor.fetchall()

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

def update_devices_names(mac_address, name):
    query = f"""
        UPDATE device_names
        SET name = '{name}'
        WHERE device_names.mac_address like '{mac_address}'
    """

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)

def insert_devices_names(mac_address, name):
    query = f"""
        INSERT INTO device_names (name, mac_address)
        VALUES ('{name}', '{mac_address}')
    """

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)

def remove_devices_names(mac_address):
    query = f"""
        DELETE FROM  device_names
        WHERE mac_address like '{mac_address}'
    """

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)

def insert_trace_table(dest_mac_address, trace_uuid):
    with global_vars.sql_lite_connection:
        global_vars.sql_lite_connection.execute(
            "INSERT INTO trace (uuid, dest_mac_address) VALUES (?, ?)",
            (trace_uuid, dest_mac_address, )
        )

def insert_hop_table(trace_uuid, hop_counter, hop_mac_address, hop_rssi):
    with global_vars.sql_lite_connection:
        global_vars.sql_lite_connection.execute(
            "INSERT INTO hop (trace_uuid, hop_counter, hop_mac_address, hop_rssi) VALUES (?, ?, ?, ?)",
            (trace_uuid, hop_counter, hop_mac_address, hop_rssi, )
        )

def insert_device_activity_table(mac_address, activity):
    with global_vars.sql_lite_connection:
        global_vars.sql_lite_connection.execute(
            "INSERT INTO device_activity (mac_address, activity) VALUES (?, ?)",
            (mac_address, activity)
        )