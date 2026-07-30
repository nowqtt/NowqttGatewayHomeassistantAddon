import json
import logging
import threading
import time

import global_vars
from nowqtt_database import (
    find_with_filters,
    count_traces,
    find_devices,
    count_devices,
    find_device_names,
    count_device_names,
    insert_devices_names,
    update_devices_names,
    remove_devices_names,
    find_current_activity_data,
    find_activity_by_mac_address,
    count_activity,
    count_current_activity_states,
    find_last_trace_of_each_device,
    get_graph_revision,
)
from collections import defaultdict


_graph_cache_lock = threading.Lock()
_graph_cache_value = None
_graph_cache_expires = 0
_graph_cache_revision = None


def fetch_devices(limit=100, offset=0):
    rows = find_devices(limit, offset)

    devices = []
    for row in rows:
        devices.append({
            "mac_address": row[0],
            "name": row[1]
        })

    result = {
        "total": count_devices(),
        "items": devices
    }

    return json.dumps(result, indent=4)

def fetch_traces(device_mac_address, last, offset=0):
    rows = find_with_filters(device_mac_address, last, offset)

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
        "total": count_traces(device_mac_address),
        "items": list(traces.values())
    }

    return json.dumps(result, indent=4)

def fetch_devices_names(mac_address=None, limit=100, offset=0):
    rows = find_device_names(mac_address, limit, offset)

    names = []
    for row in rows:
        names.append({
            "name": row[0],
            "mac_address": row[1]
        })

    result = {
        "total": count_device_names(mac_address),
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

def fetch_devices_activity(mac_address, last, offset=0):
    if mac_address is None:
        activity_data = find_current_activity_data(last, offset)
    else:
        activity_data = find_activity_by_mac_address(mac_address, last, offset)

    activity = []
    for row in activity_data:
        activity.append({
            "mac_address": row[0],
            "timestamp": row[1],
            "activity": row[2],
            "name": row[3]
        })

    current_total, online_total, offline_total = count_current_activity_states()
    result = {
        "total": current_total if mac_address is None else count_activity(mac_address),
        "online": online_total,
        "offline": offline_total,
        "items": activity
    }

    return json.dumps(result, indent=4)

def trigger_ota_update(mac_address, files):
    binary_file_bytes = None
    for _, file in files.items():
        if file.filename.lower().endswith('.bin'):
            binary_file_bytes = bytearray(file.read())
            break

    if not binary_file_bytes:
        raise ValueError("A non-empty .bin firmware file is required")
    logging.info("Starting OTA update for %s", mac_address)
    return global_vars.ota_coordinator.start_update(binary_file_bytes, mac_address)


def traces_to_edges(rows):
    traces = defaultdict(list)
    # group by uuid
    for uuid, ts, mac, rssi, hop in rows:
        traces[uuid].append({
            "mac": mac,
            "rssi": rssi,
            "hop": hop,
            "timestamp": ts
        })

    edges = {}
    for uuid, hops in traces.items():
        for i in range(len(hops) - 1):
            source = hops[i]["mac"]
            target = hops[i + 1]["mac"]
            rssi = hops[i + 1]["rssi"]
            timestamp = hops[i + 1]["timestamp"]

            edge_key = (source, target)
            current = edges.get(edge_key)
            if current is None or timestamp > current['timestamp']:
                edges[edge_key] = {
                    "uuid": uuid,
                    "source": source,
                    "target": target,
                    "rssi": rssi,
                    "timestamp": timestamp
                }

    return list(edges.values())

def fetch_graph_data():
    global _graph_cache_value, _graph_cache_expires, _graph_cache_revision
    now = time.monotonic()
    revision = get_graph_revision()
    with _graph_cache_lock:
        if (
            _graph_cache_value is not None
            and revision == _graph_cache_revision
            and now < _graph_cache_expires
        ):
            return _graph_cache_value

        devices = find_device_names(None, limit=1000)
        nodes = [
            {"label": device[0], "id": device[1], "type": "device"}
            for device in devices
        ]
        nodes.append({
            "label": "Gateway",
            "id": "c04e304b157e",
            "type": "gateway"
        })

        trace_interval = global_vars.config.get("trace_interval_seconds", 60)
        trace_freshness = max(180, int(trace_interval) * 3)
        traces = find_last_trace_of_each_device(trace_freshness, limit=1000)
        result_json = json.dumps({
            "nodes": nodes,
            "edges": traces_to_edges(traces)
        }, indent=4)
        _graph_cache_value = result_json
        _graph_cache_expires = now + 10
        _graph_cache_revision = revision
        return result_json
