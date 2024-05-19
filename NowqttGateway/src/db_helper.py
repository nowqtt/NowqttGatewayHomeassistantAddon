import json
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
            hop.hop_rssi
        FROM trace
        LEFT JOIN hop ON trace.uuid = hop.trace_uuid
    """

def find_trace_qb():
    return """
        SELECT
            trace.uuid, 
            trace.dest_mac_address, 
            trace.timestamp
        FROM trace
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
            trace.dest_mac_address
        FROM trace
    """

    cursor = global_vars.sql_lite_connection.cursor()
    cursor.execute(query)
    return cursor.fetchall()

def fetch_devices():
    rows = find_devices()

    devices = []
    for row in rows:
        devices.append(row[0])

    result = {
        "total": len(devices),
        "items": devices
    }

    # Convert data to JSON format
    json_data = json.dumps(result, indent=4)
    return json_data

def fetch_traces(device_mac_address, last):
    filters = []

    if device_mac_address is not None:
        filters.append("trace.dest_mac_address like '" + device_mac_address + "'")

    if len(filters) > 0:
        rows = find_with_filters(filters, last)
    else:
        rows = find_all()

    # Convert data to a list of dictionaries
    traces = {}
    for row in rows:
        trace_uuid = row[0]
        if trace_uuid not in traces:
            traces[trace_uuid] = {
                "uuid": row[0],
                "dest_mac_address": row[1],
                "timestamp": row[2],
                "hops": []
            }
        if row[3] is not None:  # If hop data exists
            hop_data = {
                "hop_counter": row[3],
                "hop_mac_address": row[4],
                "hop_rssi": row[5]
            }
            traces[trace_uuid]["hops"].append(hop_data)

    result = {
        "total": len(traces),
        "items": traces
    }

    # Convert data to JSON format
    json_data = json.dumps(result, indent=4)
    return json_data