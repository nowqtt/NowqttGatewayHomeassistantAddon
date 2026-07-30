from enum import Enum

global serial
global serial_transport
global mqtt_client_credentials
global config
global ota_coordinator
global mqtt_gateway
global serial_task
global background_workers
global stop_event


class SerialCommands(Enum):
    RESET = 0
    HEARTBEAT = 1
    CONFIG = 2
    STATE = 3
    COMMAND = 4
    LOG = 6
    ACK = 7


platforms = {
    'switch': {
        'state': True,
        'command': True,
    },
    'sensor': {
        'state': True,
        'command': False,
    },
    'number': {
        'state': True,
        'command': True,
    },
    'select': {
        'state': True,
        'command': True,
    },
    'binary_sensor': {
        'state': True,
        'command': False,
    },
    'cover': {
        'state': True,
        'command': True,
    }
}
