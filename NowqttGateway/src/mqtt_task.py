import logging
import global_vars
import threading
import time


def online_message_config(mqtt_client, mqtt_config_topic, mqtt_config_message):
    mqtt_client.publish(mqtt_config_topic, mqtt_config_message)


def online_message_state(mqtt_client, mqtt_state_topic, last_known_state):
    if last_known_state is not None:
        mqtt_client.publish(mqtt_state_topic, last_known_state)


class MQTTTask:
    def __init__(self,
                    mqtt_client,
                    subscriptions,
                    device_mac_address_bytearray,
                    entity_id,
                    mqtt_config_message,
                    mqtt_config_topic,
                    mqtt_state_topic):
            self.mqtt_client = mqtt_client
            self.subscriptions = subscriptions
            self.device_mac_address_bytearray = device_mac_address_bytearray
            self.entity_id = entity_id,
            self.mqtt_config_message = mqtt_config_message
            self.mqtt_config_topic = mqtt_config_topic
            self.mqtt_state_topic = mqtt_state_topic

            self.last_known_state = None

    def on_connect(self, client, userdata, flags, rc):
        logging.info("MQTT connected with result code %i", rc)

        for sub in self.subscriptions:
            self.mqtt_client.subscribe(sub)

    def on_message(self, client, userdata, msg):
        splitted_topic = msg.topic.split("/")

        logging.debug("topic: %s, msg: %s", msg.topic, msg.payload.decode("utf-8"))

        if splitted_topic[len(splitted_topic) - 1] == "com":
            handshake_message = bytearray()
            handshake_message.extend(self.device_mac_address_bytearray)
            handshake_message.append(global_vars.SerialCommands.COMMAND.value)
            handshake_message.append(self.entity_id[0])

            message = bytearray.fromhex("FF13AB00")
            message.extend(handshake_message)
            message.extend(msg.payload)
            message.append(0)

            message[4 - 1] = len(message) - 4

            global_vars.serial.write(message)
        elif msg.topic == "homeassistant/status":
            if msg.payload.decode("utf-8") == "online":
                logging.debug('online message')
                t = threading.Timer(
                    10.0,
                    online_message_config,
                    args=(self.mqtt_client,
                          self.mqtt_config_topic,
                          self.mqtt_config_message
                          )
                )
                t.daemon = True
                t.start()

                t = threading.Timer(
                    15.0,
                    online_message_state,
                    args=(self.mqtt_client,
                          self.mqtt_state_topic,
                          self.last_known_state
                          )
                )
                t.daemon = True
                t.start()

    def on_disconnect(self, client, userdata, rc):
        logging.info('MQTT device "%s" disconnected', client._client_id.decode("utf-8"))
        logging.debug('MQTT disconnecting reason %s', str(rc))

    def set_last_known_state(self, message):
        self.last_known_state = message

    def connect_to_mqtt(self):
        logging.info('connect_to_mqtt')

        try:
            self.mqtt_client.connect(global_vars.mqtt_client_credentials["address"],
                                     global_vars.mqtt_client_credentials["port"], 60)
        except ConnectionRefusedError:
            logging.info("Connection refused. Retrying in 10 seconds...")
            time.sleep(10)
            self.connect_to_mqtt()

    def start_mqtt_task(self):
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.on_disconnect = self.on_disconnect
        self.mqtt_client.set_last_known_state = self.set_last_known_state

        self.mqtt_client.username_pw_set(global_vars.mqtt_client_credentials["username"],
                                         global_vars.mqtt_client_credentials["password"])

        self.connect_to_mqtt()

        self.mqtt_client.publish(self.mqtt_config_topic, self.mqtt_config_message)

        self.mqtt_client.loop_forever()
