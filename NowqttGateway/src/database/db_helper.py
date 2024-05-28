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

    logging.info(query)

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
