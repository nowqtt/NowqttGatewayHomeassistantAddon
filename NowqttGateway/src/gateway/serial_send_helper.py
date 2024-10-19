import logging
import global_vars

def base_serial_message(service, mac_address):
    message = "FF13AB"  # Default Message start
    message += service  # nowqtt service
    message += "00"  # message length
    message += mac_address  # destination mac address

    return message

def send_serial_message(service, mac_address, serial_command_type, entity_id, payload):
    message = base_serial_message(service, mac_address)

    if serial_command_type is not None and entity_id is not None:
        message += "{:02X}".format(serial_command_type) # message type
        message += "{:02X}".format(entity_id)   # destination entity ID

    formatted_message = bytearray.fromhex(message)
    if payload is not None:
        formatted_message.extend(payload) # nowqtt message body
        formatted_message.append(0) # message ending

    formatted_message[4] = len(formatted_message) - 5   # set message length

    logging.debug('Serial message: %s', formatted_message.hex())

    global_vars.serial.write(formatted_message)

def send_ota_init_serial_message(service, mac_address, serial_command_type, binary_length):
    message = base_serial_message(service, mac_address)

    message += f"{serial_command_type:02X}"  # message type
    hex_binary_length =  f"{binary_length:08X}"
    message += ''.join([hex_binary_length[i:i+2] for i in range(0, len(hex_binary_length), 2)][::-1]) #Big to little endian

    formatted_message = bytearray.fromhex(message)
    formatted_message[4] = len(formatted_message) - 5  # set message length

    logging.info('Serial message: %s', formatted_message.hex())

    global_vars.serial.write(formatted_message)
