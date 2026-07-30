import logging
import re

import global_vars

from .serial_transport import SerialPriority


HEX_BYTE_PATTERN = re.compile(r"^[0-9a-fA-F]{2}$")
MAC_PATTERN = re.compile(r"^[0-9a-fA-F]{12}$")


def _validate_address_fields(service, mac_address):
    if not HEX_BYTE_PATTERN.fullmatch(service or ""):
        raise ValueError("Serial service must be one hexadecimal byte")
    if not MAC_PATTERN.fullmatch(mac_address or ""):
        raise ValueError("Serial destination must be a 12-digit hexadecimal MAC")


def _finalize_frame(formatted_message):
    body_length = len(formatted_message) - 5
    if body_length < 1 or body_length > 255:
        raise ValueError("Serial frame body must contain between 1 and 255 bytes")
    formatted_message[4] = body_length
    return formatted_message

def base_serial_message(service, mac_address, message_type='AB'):
    _validate_address_fields(service, mac_address)
    if message_type not in ("AB", "AC"):
        raise ValueError("Unsupported serial frame type")
    message = "FF13"  # Default Message start
    message += message_type
    message += service  # nowqtt service
    message += "00"  # message length
    message += mac_address  # destination mac address

    return message

def send_serial_message(service, mac_address, serial_command_type, entity_id, payload, priority=SerialPriority.COMMAND):
    message = base_serial_message(service, mac_address)

    if serial_command_type is not None and entity_id is not None:
        message += "{:02X}".format(serial_command_type) # message type
        message += "{:02X}".format(entity_id)   # destination entity ID

    formatted_message = bytearray.fromhex(message)
    if payload is not None:
        formatted_message.extend(payload) # nowqtt message body
        formatted_message.append(0) # message ending

    _finalize_frame(formatted_message)

    logging.debug('Serial message: %s', formatted_message.hex())

    return global_vars.serial_transport.send(formatted_message, priority)

def send_ota_init_serial_message(service, mac_address, serial_command_type, binary_length):
    message = base_serial_message(service, mac_address)

    message += f"{serial_command_type:02X}"  # message type
    hex_binary_length =  f"{binary_length:08X}"
    message += ''.join([hex_binary_length[i:i+2] for i in range(0, len(hex_binary_length), 2)][::-1]) #Big to little endian

    formatted_message = bytearray.fromhex(message)
    _finalize_frame(formatted_message)

    logging.debug('OTA init serial message: %s', formatted_message.hex())

    return global_vars.serial_transport.send(formatted_message, SerialPriority.OTA)

def send_ota_data_serial_message(service, mac_address, serial_command_type, packet_number, payload):
    message = base_serial_message(service, mac_address, "AC")

    message += f"{serial_command_type:02X}"  # message type
    packet_number_length = f"{packet_number:08X}"
    message += ''.join([packet_number_length[i:i + 2] for i in range(0, len(packet_number_length), 2)][::-1])  # Big to little endian

    formatted_message = bytearray.fromhex(message)
    formatted_message.extend(payload)
    _finalize_frame(formatted_message)

    logging.debug('OTA data serial message: %s', formatted_message.hex())

    return global_vars.serial_transport.send(formatted_message, SerialPriority.OTA)


def command_to_serial(device_mac_address, entity_id):
    def handler(payload):
        if not send_serial_message(
            "01",
            device_mac_address,
            global_vars.SerialCommands.COMMAND.value,
            entity_id,
            payload,
            SerialPriority.COMMAND,
        ):
            raise RuntimeError("Serial command queue is full")

    return handler
