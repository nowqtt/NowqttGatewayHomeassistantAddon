import json
import logging
import threading

import paho.mqtt.client as mqtt

import global_vars

from .serial_transport import SerialPriority
from .formatter import GATEWAY_AVAILABILITY_TOPIC, get_device_availability_topic


class MQTTGateway:
    def __init__(self):
        self._client = mqtt.Client(client_id="nowqtt_gateway")
        self._lock = threading.RLock()
        self._connected = threading.Event()
        self._started = False
        self._republish_timer = None
        self._entities_by_command_topic = {}
        self._entities_by_key = {}
        self._pending_config_removals = set()
        self._offline_availability_topics = set()
        self._management_config = self._build_management_config()

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.username_pw_set(
            global_vars.mqtt_client_credentials["username"],
            global_vars.mqtt_client_credentials["password"],
        )
        self._client.will_set(
            self._management_config["availability_topic"],
            payload="offline",
            qos=1,
            retain=True,
        )
        try:
            self._client.max_queued_messages_set(1000)
        except RuntimeError:
            pass

    def start(self):
        with self._lock:
            if self._started:
                return
            self._started = True

        self._client.connect_async(
            global_vars.mqtt_client_credentials["address"],
            global_vars.mqtt_client_credentials["port"],
            60,
        )
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._client.loop_start()

    def stop(self):
        with self._lock:
            if not self._started:
                return
            timer = self._republish_timer
            self._republish_timer = None
            self._started = False
        if timer is not None:
            timer.cancel()

        self._client.publish(
            self._management_config["availability_topic"],
            "offline",
            qos=1,
            retain=True,
        )
        self._client.disconnect()
        self._client.loop_stop()

    def register_entity(self, key, config_topic, mqtt_config, command_handler=None):
        entity = MQTTEntity(self, key, config_topic, mqtt_config)
        with self._lock:
            previous = self._entities_by_key.get(key)
            if previous is not None and previous.command_topic:
                self._entities_by_command_topic.pop(previous.command_topic, None)
                if self._connected.is_set():
                    self._client.unsubscribe(previous.command_topic)
            self._entities_by_key[key] = entity
            self._pending_config_removals.discard(config_topic)
            if entity.command_topic and command_handler is not None:
                self._entities_by_command_topic[entity.command_topic] = command_handler
                if self._connected.is_set():
                    self._client.subscribe(entity.command_topic)

        if previous is not None and previous.config_topic != config_topic:
            self._remove_config(previous.config_topic)
            previous.publish_availability("offline")
        entity.publish_config()
        if previous is not None:
            entity.publish_availability("online")
        return entity

    def update_entity(self, entity, config_topic, mqtt_config, command_handler=None):
        with self._lock:
            old_command_topic = entity.command_topic
            if old_command_topic:
                self._entities_by_command_topic.pop(old_command_topic, None)
                if self._connected.is_set():
                    self._client.unsubscribe(old_command_topic)

            old_config_topic, old_availability_topic = entity.update_config(
                config_topic, mqtt_config
            )
            self._pending_config_removals.discard(entity.config_topic)
            if entity.command_topic and command_handler is not None:
                self._entities_by_command_topic[entity.command_topic] = command_handler
                if self._connected.is_set():
                    self._client.subscribe(entity.command_topic)

        if old_config_topic != entity.config_topic:
            self._remove_config(old_config_topic)
        if old_availability_topic != entity.availability_topic:
            self.publish(old_availability_topic, "offline", qos=1, retain=True)
            entity.publish_availability("online")
        entity.publish_config()

    def unregister_entity(self, key, expected_entity=None, publish_availability=True):
        with self._lock:
            entity = self._entities_by_key.get(key)
            if entity is None:
                return False
            if expected_entity is not None and entity is not expected_entity:
                return False
            self._entities_by_key.pop(key, None)
            if entity.command_topic:
                self._entities_by_command_topic.pop(entity.command_topic, None)
                if self._connected.is_set():
                    self._client.unsubscribe(entity.command_topic)
        if publish_availability:
            entity.publish_availability("offline")
        self._remove_config(entity.config_topic)
        return True

    def is_connected(self):
        return self._connected.is_set()

    def publish(self, topic, payload, qos=0, retain=False):
        result = self._client.publish(topic, payload, qos=qos, retain=retain)
        if result.rc not in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
            logging.warning("MQTT publish failed for %s with rc=%s", topic, result.rc)
        return result.rc in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN)

    def publish_device_availability(self, topic, state):
        with self._lock:
            if state == "online":
                self._offline_availability_topics.discard(topic)
            else:
                self._offline_availability_topics.add(topic)
        return self.publish(topic, state, qos=1, retain=True)

    def _remove_config(self, topic):
        with self._lock:
            self._pending_config_removals.add(topic)
        return self.publish(topic, "", qos=1, retain=True)

    def _on_connect(self, client, userdata, flags, rc):
        if rc != 0:
            logging.error("MQTT connection rejected with rc=%s", rc)
            return
        with self._lock:
            if not self._started:
                client.disconnect()
                return

        self._connected.set()
        logging.info("Shared MQTT gateway connected")
        client.subscribe("homeassistant/status")
        client.subscribe("homeassistant/button/nowqtt/trigger_reset/com")

        with self._lock:
            command_topics = list(self._entities_by_command_topic)
        for topic in command_topics:
            client.subscribe(topic)

        self._publish_management_config()
        self._republish_all()

    def _on_disconnect(self, client, userdata, rc):
        self._connected.clear()
        if rc:
            logging.warning("Shared MQTT gateway disconnected unexpectedly: rc=%s", rc)
        else:
            logging.info("Shared MQTT gateway disconnected")

    def _on_message(self, client, userdata, message):
        if message.topic == "homeassistant/status":
            if message.payload == b"online":
                self._schedule_republish()
            return

        if message.topic == "homeassistant/button/nowqtt/trigger_reset/com":
            if message.payload == b"PRESS":
                logging.info("Sending mesh reset message")
                if not global_vars.serial_transport.send(
                    bytearray.fromhex("FF13ACFE00"), SerialPriority.CONTROL
                ):
                    logging.error("Unable to queue mesh reset control frame")
            return

        with self._lock:
            handler = self._entities_by_command_topic.get(message.topic)
        if handler is not None:
            try:
                handler(message.payload)
            except Exception:
                logging.exception("MQTT command handler failed for %s", message.topic)

    def _schedule_republish(self):
        with self._lock:
            if not self._started:
                return
            if self._republish_timer is not None:
                self._republish_timer.cancel()
            self._republish_timer = threading.Timer(2.0, self._republish_all)
            self._republish_timer.daemon = True
            self._republish_timer.start()

    def _republish_all(self):
        with self._lock:
            self._republish_timer = None
            if not self._started:
                return
            entities = list(self._entities_by_key.values())
            config_removals = list(self._pending_config_removals)
            offline_topics = list(self._offline_availability_topics)
        for topic in config_removals:
            self.publish(topic, "", qos=1, retain=True)
        for topic in offline_topics:
            self.publish(topic, "offline", qos=1, retain=True)
        self._publish_management_config()
        for entity in entities:
            with self._lock:
                if (
                    not self._started
                    or self._entities_by_key.get(entity.key) is not entity
                ):
                    continue
                entity.publish_config()
                entity.publish_availability("online")
                entity.republish_state()

    def _publish_management_config(self):
        with self._lock:
            if not self._started:
                return
            self.publish(
                "homeassistant/button/nowqtt/trigger_reset/config",
                json.dumps(self._management_config),
                retain=True,
            )
            self.publish(
                self._management_config["availability_topic"],
                "online",
                qos=1,
                retain=True,
            )

    @staticmethod
    def _build_management_config():
        device = {
            "identifiers": "NowQtt",
            "manufacturer": "NowQtt",
            "name": "NowQtt",
        }
        return {
            "availability_topic": GATEWAY_AVAILABILITY_TOPIC,
            "command_topic": "homeassistant/button/nowqtt/trigger_reset/com",
            "name": "NowQtt Trigger Reset",
            "unique_id": "nowqtt_trigger_reset",
            "object_id": "nowqtt_trigger_reset",
            "device_class": "restart",
            "device": device,
        }


class MQTTEntity:
    def __init__(self, gateway, key, config_topic, mqtt_config):
        self._gateway = gateway
        self.key = key
        self.config_topic = config_topic
        self.config = dict(mqtt_config)
        self.state_topic = mqtt_config.get("state_topic")
        self.availability_topic = get_device_availability_topic(mqtt_config)
        self.command_topic = mqtt_config.get("command_topic")
        self.last_known_state = None

    def update_config(self, config_topic, mqtt_config):
        old_config_topic = self.config_topic
        old_availability_topic = self.availability_topic
        self.config_topic = config_topic
        self.config = dict(mqtt_config)
        self.state_topic = mqtt_config.get("state_topic")
        self.availability_topic = get_device_availability_topic(mqtt_config)
        self.command_topic = mqtt_config.get("command_topic")
        return old_config_topic, old_availability_topic

    def publish_state(self, message):
        self.last_known_state = message
        if self.state_topic is not None:
            self._gateway.publish(self.state_topic, message)

    def republish_state(self):
        if self.last_known_state is not None:
            self.publish_state(self.last_known_state)

    def publish_config(self):
        self._gateway.publish(self.config_topic, json.dumps(self.config), retain=True)

    def publish_availability(self, state):
        self._gateway.publish_device_availability(self.availability_topic, state)
