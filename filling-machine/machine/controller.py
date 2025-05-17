# machine/controller.py

import threading
import time
import logging
from datetime import datetime
from typing import Any

from config import Config
from machine.modbus_interface import ModbusInterface
from machine.mqtt_client import MqttClient

class MachineController:
    """
    Coordinates the filling machine: hardware control, telemetry, and filling logic.
    """

    STATE_WAITING_FOR_MOULD = "waiting_for_mould"
    STATE_CONFIRMING_MOULD = "confirming_mould"
    STATE_FILL_LEFT_FAST   = "fill_left_fast"
    STATE_FILL_LEFT_SLOW   = "fill_left_slow"
    STATE_PREP_RIGHT       = "prep_right"
    STATE_FILL_RIGHT_FAST  = "fill_right_fast"
    STATE_FILL_RIGHT_SLOW  = "fill_right_slow"
    STATE_WAIT_REMOVAL     = "wait_removal"

    def __init__(self, config: Config, modbus: ModbusInterface, mqtt: MqttClient):
        self.config = config
        self.modbus = modbus
        self.mqtt   = mqtt

        # Default user parameters
        self.vfd_state      = 0          # VFD off initially
        self.vfd_speed      = 0          # 0–255 units (0–2.55Hz)
        self.valve1         = False      # left valve state
        self.valve2         = False      # right valve state
        self.actual_weight  = 0.0        # last read weight
        self.desired_volume = config.get("Food_Service")
        self.mould_weight   = config.get("Food_Service_mould")
        self.filling_status = 0          # custom status code

        # Load-cell & timing parameters from config
        self._mould_tol        = config.get("mould_tolerance")      # ±10% example
        self._fill_tol         = config.get("fill_tolerance")       # ±15%
        self._removal_tol      = config.get("removal_tolerance")    # e.g. 0.02 kg
        self._read_interval    = config.get("loadcell_interval")    # e.g. 0.1s
        self._valve_delay      = config.get("valve_start_delay")    # e.g. 0.1s
        self._post_fill_delay  = config.get("post_fill_delay")      # e.g. 1.0s
        self._confirm_readings = config.get("confirm_readings")     # e.g. 3
        self._confirm_removals = config.get("confirm_removals")     # e.g. 3
        self.speed_fast        = config.get("fast_speed")           # e.g. 150.0 Hz
        self.speed_slow        = config.get("slow_speed")           # e.g. 50.0 Hz

        # State machine internals
        self._state         = self.STATE_WAITING_FOR_MOULD
        self._tare_weight   = 0.0
        self._consec_count  = 0

        # Thread control
        self.kill_all       = threading.Event()
        self._threads       = []

    def select_flavour(self, name: str) -> None:
        """
        Change target volume and mould weight based on flavour.
        """
        self.desired_volume = self.config.get(name)
        self.mould_weight   = self.config.get(f"{name}_mould")
        logging.info(f"Flavour selected: {name}, volume={self.desired_volume}, mould={self.mould_weight}")

    def start(self) -> None:
        """
        Start background threads for modbus, monitoring, and filling loops.
        """
        for fn in (self._modbus_loop, self._monitor_loop, self._filling_loop):
            t = threading.Thread(target=fn, daemon=True)
            self._threads.append(t)
            t.start()
        logging.info("MachineController: threads started")

    def stop(self) -> None:
        """
        Signal threads to stop and wait for them. Ensure clean shutdown.
        """
        self.kill_all.set()
        for t in self._threads:
            t.join()

        # Hardware shutdown
        try:
            self.modbus.set_vfd_speed(0)
            self.modbus.set_vfd_state(0)
            self.modbus.set_valve("left",  "close")
            self.modbus.set_valve("right", "close")
        except Exception:
            logging.exception("Error during hardware shutdown")

        # Always disconnect MQTT
        try:
            self.mqtt.disconnect()
        except Exception:
            logging.exception("Error during MQTT shutdown")

        logging.info("MachineController: stopped")

    def _modbus_loop(self) -> None:
        """
        Apply current VFD/valve state and read the load cell.
        """
        while not self.kill_all.is_set():
            try:
                self.modbus.set_vfd_state(self.vfd_state)
                self.modbus.set_vfd_speed(self.vfd_speed)
                self.modbus.set_valve("left",  "open" if self.valve1 else "close")
                self.modbus.set_valve("right", "open" if self.valve2 else "close")
                self.actual_weight = self.modbus.read_load_cell()
            except Exception:
                logging.exception("Error in modbus loop")
            time.sleep(self._read_interval)

    def _monitor_loop(self) -> None:
        """
        Publish telemetry over MQTT.
        """
        while not self.kill_all.is_set():
            try:
                self.mqtt.publish("FillingMachine/ActualWeight", self.actual_weight)
                self.mqtt.publish("FillingMachine/VFDState",      self.vfd_state)
                self.mqtt.publish("FillingMachine/VFDSpeed",      self.vfd_speed)
                self.mqtt.publish("FillingMachine/Valve1State",   int(self.valve1))
                self.mqtt.publish("FillingMachine/Valve2State",   int(self.valve2))
                self.mqtt.publish("FillingMachine/FillStatus",    self.filling_status)
            except Exception:
                logging.exception("Error in monitor loop")
            time.sleep(0.1)

    def _detect_mould(self) -> bool:
        """
        Return True if the scale weight is within mould tolerance and waiting state.
        """
        # Only detect when waiting for a mould
        if self._state != self.STATE_WAITING_FOR_MOULD:
            return False
        w = self.actual_weight
        # Check if within mould tolerance
        return abs(w - self.mould_weight) <= self.mould_weight * self._mould_tol

    def _filling_loop(self) -> None:
        """
        Full multi-stage fill state machine.
        """
        while not self.kill_all.is_set():
            try:
                w = self.actual_weight

                # 1) Waiting until a mould tray is placed
                if self._state == self.STATE_WAITING_FOR_MOULD:
                    if abs(w - self.mould_weight) <= self.mould_weight * self._mould_tol:
                        self._consec_count = 1
                        self._state = self.STATE_CONFIRMING_MOULD

                # 1.1) Confirm consecutive mould readings
                elif self._state == self.STATE_CONFIRMING_MOULD:
                    if abs(w - self.mould_weight) <= self.mould_weight * self._mould_tol:
                        self._consec_count += 1
                        if self._consec_count >= self._confirm_readings:
                            # Record tare and start left fill
                            self._tare_weight = w
                            time.sleep(self._valve_delay)
                            self.valve1     = True
                            self.vfd_state  = 6
                            self.vfd_speed  = int(self.speed_fast * 100)
                            self._state     = self.STATE_FILL_LEFT_FAST
                    else:
                        self._state = self.STATE_WAITING_FOR_MOULD

                # 2) Fast-fill left until within fill tolerance
                elif self._state == self.STATE_FILL_LEFT_FAST:
                    if (w - self._tare_weight) >= self.desired_volume * (1 - self._fill_tol):
                        self.vfd_speed = int(self.speed_slow * 100)
                        self._state    = self.STATE_FILL_LEFT_SLOW

                # 3) Slow-fill left until target reached
                elif self._state == self.STATE_FILL_LEFT_SLOW:
                    if (w - self._tare_weight) >= self.desired_volume:
                        self.vfd_speed = 0
                        self.vfd_state = 0
                        time.sleep(self._post_fill_delay)
                        self.valve1 = False
                        time.sleep(self._post_fill_delay)
                        # Prepare right fill
                        self._state = self.STATE_PREP_RIGHT

                # 4) Prep right: open valve, start fast fill
                elif self._state == self.STATE_PREP_RIGHT:
                    self._consec_count = 0
                    self._tare_weight  = w
                    self.valve2        = True
                    self.vfd_state     = 6
                    self.vfd_speed     = int(self.speed_fast * 100)
                    self._state        = self.STATE_FILL_RIGHT_FAST

                # 5) Fast-fill right
                elif self._state == self.STATE_FILL_RIGHT_FAST:
                    if (w - self._tare_weight) >= self.desired_volume * (1 - self._fill_tol):
                        self.vfd_speed = int(self.speed_slow * 100)
                        self._state    = self.STATE_FILL_RIGHT_SLOW

                # 6) Slow-fill right until done
                elif self._state == self.STATE_FILL_RIGHT_SLOW:
                    if (w - self._tare_weight) >= self.desired_volume:
                        self.vfd_speed = 0
                        self.vfd_state = 0
                        time.sleep(self._post_fill_delay)
                        self.valve2 = False
                        self._state  = self.STATE_WAIT_REMOVAL
                        self._consec_count = 0

                # 7) Wait for tray removal (multiple zero readings)
                elif self._state == self.STATE_WAIT_REMOVAL:
                    if w <= self._removal_tol:
                        self._consec_count += 1
                        if self._consec_count >= self._confirm_removals:
                            # Re-tare for next cycle
                            self._tare_weight = w
                            self._state       = self.STATE_WAITING_FOR_MOULD
                    else:
                        self._consec_count = 0

            except Exception:
                logging.exception("Error in filling loop")

            time.sleep(self._read_interval)