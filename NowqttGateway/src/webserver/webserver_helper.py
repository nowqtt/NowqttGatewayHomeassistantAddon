import json
import logging

from database import find_with_filters, find_all, find_devices, find_device_names, update_devices_names, \
    insert_devices_names, remove_devices_names


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

    if len(filters) > 0 or last is not None:
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
        "items": list(traces.values())
    }

    # Convert data to JSON format
    json_data = json.dumps(result, indent=4)
    return json_data

def fetch_devices_names(mac_address = None):
    rows = find_device_names(mac_address)

    names = []
    for row in rows:
        names.append({
            "name": row[0],
            "mac_address": row[1]
        })

    result = {
        "total": len(names),
        "items": names
    }

    # Convert data to JSON format
    json_data = json.dumps(result, indent=4)
    return json_data

def patch_devices_names(mac_address, name):
    rows = find_device_names(mac_address)

    if len(rows) != 0:
        update_devices_names(mac_address, name)
    else:
        insert_devices_names(mac_address, name)

def delete_devices_names(mac_address):
    remove_devices_names(mac_address)