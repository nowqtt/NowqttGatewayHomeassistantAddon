import logging
import global_vars

def send_serial_message(service, mac_address, serial_command_type, entity_id, payload):
    message = "FF13AB"  # Default Message start
    message += service # nowqtt service
    message += "00" # message length
    message += mac_address  # destination mac address

    if serial_command_type is not None and entity_id is not None:
        message += "{:02d}".format(serial_command_type) # message type
        message += "{:02X}".format(entity_id)   # destination entity ID

    formatted_message = bytearray.fromhex(message)
    if payload is not None:
        formatted_message.extend(payload) # nowqtt message body
        formatted_message.append(0) # message ending

    formatted_message[4] = len(formatted_message) - 5   # set message length

    logging.debug('Serial message: %s', formatted_message.hex())

    global_vars.serial.write(formatted_message)
