# machine/mqtt_client.py

import paho.mqtt.client as mqtt
import logging

class MqttClient:
    """
    Wraps Paho MQTT for simple, safe publishing.
    """

    def __init__(self, broker: str, client_id: str = "Filling_Machine", keepalive: int = 60):
        self._client = mqtt.Client(client_id)
        try:
            # Connect and start the network loop in its own thread
            self._client.connect(broker, keepalive=keepalive)
            self._client.loop_start()
        except Exception as e:
            logging.exception(f"MQTT connect failed ({broker}): {e}")

    def publish(self, topic: str, payload, qos: int = 0, retain: bool = False):
        """
        Publish a message to a topic, swallowing errors but logging them.
        """
        try:
            self._client.publish(topic, payload, qos=qos, retain=retain)
        except Exception as e:
            logging.exception(f"MQTT publish error ({topic}): {e}")

    def disconnect(self):
        """
        Stop the network loop and disconnect cleanly.
        """
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception as e:
            logging.exception(f"MQTT disconnect error: {e}")