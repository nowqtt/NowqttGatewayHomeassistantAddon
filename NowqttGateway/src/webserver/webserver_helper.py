import json
import logging

import global_vars
from nowqtt_database import (
    find_with_filters,
    find_devices,
    find_device_names,
    insert_devices_names,
    update_devices_names,
    remove_devices_names,
    find_current_activity_data,
    find_activity_by_mac_address,
    find_active_or_inactive_devices
)
from ota import OtaManager


def fetch_devices():
    rows = find_devices()

    devices = []
    for row in rows:
        devices.append({
            "mac_address": row[0],
            "name": row[1]
        })

    result = {
        "total": len(devices),
        "items": devices
    }

    return json.dumps(result, indent=4)

def fetch_traces(device_mac_address, last):
    filters = []

    if device_mac_address is not None:
        filters.append("trace.dest_mac_address like '" + device_mac_address + "'")

    rows = find_with_filters(filters, last)

    # Convert data to a list of dictionaries
    traces = {}
    for row in rows:
        trace_uuid = row[0]
        #Fill root object
        if trace_uuid not in traces:
            traces[trace_uuid] = {
                "uuid": row[0],
                "dest_mac_address": row[1],
                "timestamp": row[2],
                "hops": []
            }

        #Fill name to root object
        if traces[trace_uuid]['dest_mac_address'] == row[4]:
            traces[trace_uuid]['name'] = row[6]

        #Fill hop object
        if row[3] is not None:  # If hop data exists
            hop_data = {
                "hop_counter": row[3],
                "hop_mac_address": row[4],
                "name": row[6],
                "hop_rssi": row[5],
                "hop_dest_seq": row[7],
                "route_age": row[8],
                "hop_count": row[9]
            }
            traces[trace_uuid]["hops"].append(hop_data)

    result = {
        "total": len(traces),
        "items": list(traces.values())
    }

    return json.dumps(result, indent=4)

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

    return json.dumps(result, indent=4)

def patch_devices_names(mac_address, name):
    rows = find_device_names(mac_address)

    if len(rows) != 0:
        update_devices_names(mac_address, name, 1)
    else:
        insert_devices_names(mac_address, name, 1)

def delete_devices_names(mac_address):
    remove_devices_names(mac_address)

def fetch_devices_activity(mac_address, last):
    if mac_address is None:
        activity_data = find_current_activity_data()
    else:
        activity_data = find_activity_by_mac_address(mac_address, last)

    activity = []
    for row in activity_data:
        activity.append({
            "mac_address": row[0],
            "timestamp": row[1],
            "activity": row[2],
            "name": row[3]
        })

    result = {
        "total": len(activity),
        "online": len(find_active_or_inactive_devices(1)),
        "offline": len(find_active_or_inactive_devices(0)),
        "items": activity
    }

    return json.dumps(result, indent=4)

def trigger_ota_update(mac_address, files):
    #TODO test if mac address is valid
    logging.info(mac_address)

    binary_file_bytes = None
    for filename, file in files.items():
        if file.filename.endswith('.bin'):
            binary_file_bytes = bytearray(file.read())
            break

    if binary_file_bytes is not None:
        global_vars.ota_queue[mac_address] = OtaManager(binary_file_bytes, mac_address)
        global_vars.ota_queue[mac_address].init_ota()