

import pytest
import logging
import paho.mqtt.client as real_mqtt

from machine.mqtt_client import MqttClient

class DummyClient:
    """
    Fake Paho MQTT Client to capture connect, publish, loop and disconnect calls.
    """
    def __init__(self, client_id, **kwargs):
        self.client_id = client_id
        self.connected = False
        self.loop_started = False
        self.publishes = []
        self.loop_stopped = False
        self.disconnected = False

    def connect(self, broker, keepalive=60):
        self.connected = True

    def loop_start(self):
        self.loop_started = True

    def publish(self, topic, payload, qos=0, retain=False):
        self.publishes.append((topic, payload, qos, retain))

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

@pytest.fixture(autouse=True)
def patch_mqtt_client(monkeypatch):
    """
    Replace paho.mqtt.client.Client with DummyClient for all tests.
    """
    monkeypatch.setattr(real_mqtt, "Client", lambda client_id: DummyClient(client_id))

def test_init_connects_and_starts_loop():
    mqtt = MqttClient("broker_address", client_id="testid", keepalive=30)
    # Underlying client should have connected and started loop
    assert mqtt._client.connected is True
    assert mqtt._client.loop_started is True

def test_disconnect_stops_loop_and_disconnects():
    mqtt = MqttClient("broker_address")
    mqtt.disconnect()
    assert mqtt._client.loop_stopped is True
    assert mqtt._client.disconnected is True

def test_publish_success(caplog):
    caplog.set_level(logging.ERROR)
    mqtt = MqttClient("broker_address")
    mqtt.publish("topic/name", "payload", qos=1, retain=True)
    # Should record the publish in DummyClient
    assert ("topic/name", "payload", 1, True) in mqtt._client.publishes

def test_publish_failure_logs(monkeypatch, caplog):
    # Create a client whose publish method raises
    class FailingClient(DummyClient):
        def publish(self, topic, payload, qos=0, retain=False):
            raise RuntimeError("fail")

    monkeypatch.setattr(real_mqtt, "Client", lambda client_id: FailingClient(client_id))
    caplog.set_level(logging.ERROR)
    mqtt = MqttClient("broker_address")
    mqtt.publish("bad/topic", "data")
    # Ensure error was logged
    assert "MQTT publish error (bad/topic)" in caplog.text