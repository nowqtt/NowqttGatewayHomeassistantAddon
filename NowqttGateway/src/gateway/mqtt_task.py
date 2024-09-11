import logging
import global_vars
import threading
import time

from .serial_send_helper import send_serial_message


def online_message_config(mqtt_client, mqtt_config_topic, mqtt_config_message):
    mqtt_client.publish(mqtt_config_topic, mqtt_config_message)


def online_message_state(mqtt_client, mqtt_state_topic, last_known_state):
    if last_known_state is not None:
        mqtt_client.publish(mqtt_state_topic, last_known_state)


class MQTTTask:
    def __init__(self,
                 mqtt_client,
                 subscriptions,
                 device_mac_address,
                 entity_id,
                 mqtt_config_message,
                 mqtt_config_topic,
                 mqtt_state_topic):
        self.mqtt_client = mqtt_client
        self.subscriptions = subscriptions
        self.device_mac_address = device_mac_address
        self.entity_id = entity_id,
        self.mqtt_config_message = mqtt_config_message
        self.mqtt_config_topic = mqtt_config_topic
        self.mqtt_state_topic = mqtt_state_topic

        self.last_known_state = None

    def on_connect(self, client, userdata, flags, rc):
        logging.info('Device %s connected to mqtt', self.mqtt_client._client_id.decode("utf-8"))

        for sub in self.subscriptions:
            self.mqtt_client.subscribe(sub)

    def on_message(self, client, userdata, msg):
        splitted_topic = msg.topic.split("/")

        logging.debug("topic: %s, msg: %s", msg.topic, msg.payload.decode("utf-8"))

        if splitted_topic[len(splitted_topic) - 1] == "com":
            send_serial_message(
                "01",
                self.device_mac_address,
                global_vars.SerialCommands.COMMAND.value,
                self.entity_id[0],
                msg.payload
            )
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

        #TODO add last will to set avail topic to offline
        #self.mqtt_client.will_set(get_availability_topic(), payload="offline", qos=0, retain=True)

        self.mqtt_client.username_pw_set(global_vars.mqtt_client_credentials["username"],
                                         global_vars.mqtt_client_credentials["password"])

        self.connect_to_mqtt()

        self.mqtt_client.publish(self.mqtt_config_topic, self.mqtt_config_message)

        self.mqtt_client.loop_forever()
