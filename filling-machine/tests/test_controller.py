import threading
import time
import pytest

from config import Config
from machine.controller import MachineController

# Dummy implementations to inject into the controller
class DummyModbus:
    def __init__(self):
        self.vfd_states = []
        self.vfd_speeds = []
        self.valve_actions = []
    def set_vfd_state(self, state):
        self.vfd_states.append(state)
    def set_vfd_speed(self, speed):
        self.vfd_speeds.append(speed)
    def set_valve(self, valve, action):
        self.valve_actions.append((valve, action))
    def read_load_cell(self):
        return 0.0  # constant for loop tests

class DummyMqtt:
    def __init__(self):
        self.published = []
        self.disconnected = False
    def publish(self, topic, payload):
        self.published.append((topic, payload))
    def disconnect(self):
        self.disconnected = True

@pytest.fixture
def controller():
    # Use real config.json for parameters
    cfg = Config()
    modbus = DummyModbus()
    mqtt   = DummyMqtt()
    ctrl = MachineController(cfg, modbus, mqtt)
    return ctrl

def test_select_flavour(controller):
    # Default flavour from config
    default_vol   = controller.config.volumes["Food_Service"]
    default_mould = controller.config.mould_weights["Food_Service"]
    assert controller.desired_volume == pytest.approx(default_vol)
    assert controller.mould_weight   == pytest.approx(default_mould)
    # Change to 'Brie'
    controller.select_flavour("Brie")
    assert controller.desired_volume == pytest.approx(controller.config.volumes["Brie"])
    assert controller.mould_weight   == pytest.approx(controller.config.mould_weights["Brie"])

def test_detect_mould_logic(controller):
    tol = controller._mould_tol
    mould_wt = controller.mould_weight
    controller._state = controller.STATE_WAITING_FOR_MOULD
    # below lower bound
    controller.actual_weight = mould_wt * (1 - tol) - 0.01
    assert controller._detect_mould() is False
    # within tolerance
    controller.actual_weight = mould_wt * (1 - tol) + 0.01
    assert controller._detect_mould() is True
    # not in WAITING state
    controller._state = controller.STATE_CONFIRMING_MOULD
    assert controller._detect_mould() is False

def test_modbus_loop_writes(controller):
    # Run one iteration of modbus loop
    controller.kill_all.clear()
    t = threading.Thread(target=controller._modbus_loop, daemon=True)
    t.start()
    time.sleep(0.05)
    controller.kill_all.set()
    t.join(timeout=1.0)
    # Check that at least one VFD state and speed was written
    assert controller.modbus.vfd_states
    assert controller.modbus.vfd_speeds
    # Check valve commands occurred (open/close possible)
    assert any(valve in ("left","right","both") for valve, _ in controller.modbus.valve_actions)

def test_monitor_loop_publishes(controller):
    controller.kill_all.clear()
    t = threading.Thread(target=controller._monitor_loop, daemon=True)
    t.start()
    time.sleep(0.05)
    controller.kill_all.set()
    t.join(timeout=1.0)
    # Expect topics for ActualWeight and VFDState at least
    topics = [topic for topic, _ in controller.mqtt.published]
    assert "FillingMachine/ActualWeight" in topics
    assert "FillingMachine/VFDState"    in topics

def test_stop_cleanup(controller):
    # Ensure stop turns off hardware and disconnects MQTT
    # Preload some state
    controller.modbus.vfd_states.clear()
    controller.modbus.vfd_speeds.clear()
    controller.modbus.valve_actions.clear()
    controller.mqtt.disconnected = False
    controller.stop()
    # After stop, expect vfd speed 0 and state 0 commands
    assert 0 in controller.modbus.vfd_speeds
    assert 0 in controller.modbus.vfd_states
    # Valves closed
    assert ("left","close") in controller.modbus.valve_actions
    assert ("right","close") in controller.modbus.valve_actions
    # MQTT disconnected
    assert controller.mqtt.disconnected is True
