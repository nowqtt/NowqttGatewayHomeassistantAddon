from enum import Enum

global serial
global mqtt_client_credentials
global config


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
