# machine/controller.py

import threading
import time
import logging
from datetime import datetime
from typing import Any

import minimalmodbus
from minimalmodbus import NoResponseError

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
        
        # VFD command codes from config
        self.vfd_run_cmd  = config.get("vfd_run_command")
        self.vfd_stop_cmd = config.get("vfd_stop_command")

        # Default user parameters
        self.vfd_state      = self.vfd_stop_cmd   # VFD off initially

        # Default user parameters
        self.vfd_speed      = 0          # 0–255 units (0–2.55Hz)
        self.valve1         = False      # left valve state
        self.valve2         = False      # right valve state
        self.actual_weight  = 0.0        # last read weight
        self.desired_volume = config.get("Food_Service")
        # Tare weight for the default flavour
        self.mould_weight   = config.mould_weights.get("Food_Service")
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

        # Modbus polling intervals
        self._vfd_interval   = config.get("vfd_interval")    # e.g. 0.05s
        self._scale_interval = config.get("scale_interval")  # e.g. 0.02s
        self._valve_interval = config.get("valve_interval")  # e.g. 0.1s

        self.speed_fast        = config.get("fast_speed")           # e.g. 150.0 Hz
        self.speed_slow        = config.get("slow_speed")           # e.g. 50.0 Hz

        # State machine internals
        self._state         = self.STATE_WAITING_FOR_MOULD
        self._tare_weight   = 0.0
        self._consec_count  = 0

        # Thread control
        self.kill_all       = threading.Event()
        self._threads       = []
        
        # Cleaning control
        self._clean_stop   = threading.Event()
        self._clean_thread = None

        # Pour tracking
        self._left_tare = None
        self._right_tare = None
        self._mould_tare = None  # the weight when tray + moulds first detected

    def select_flavour(self, name: str) -> None:
        """
        Change target volume and mould weight based on flavour.
        """
        self.desired_volume = self.config.get(name)
        # Update mould weight from nested mould_weights
        self.mould_weight   = self.config.mould_weights.get(name)
        logging.info(f"Flavour selected: {name}, volume={self.desired_volume}, mould={self.mould_weight}")

    @property
    def current_left_pour(self) -> float:
        """
        How much has been poured into the left mould so far (clamped to [0, desired_volume]).
        """
        if self._left_tare is None:
            return 0.0
        poured = self.actual_weight - self._left_tare
        return max(0.0, min(self.desired_volume, poured))

    @property
    def current_right_pour(self) -> float:
        """
        How much has been poured into the right mould so far (clamped to [0, desired_volume]).
        """
        if self._right_tare is None:
            return 0.0
        poured = self.actual_weight - self._right_tare
        return max(0.0, min(self.desired_volume, poured))

    @property
    def mould_tare_weight(self) -> float:
        """Weight of tray + moulds when first placed (before filling)."""
        return 0.0 if self._mould_tare is None else self._mould_tare

    def start(self) -> None:
        """
        Start background threads for modbus, monitoring, and filling loops.
        """
        for fn in (self._vfd_loop, self._valve_loop, self._scale_loop, self._monitor_loop, self._filling_loop):
            t = threading.Thread(target=fn, daemon=True)
            self._threads.append(t)
            t.start()
        logging.info("MachineController: threads started")

    def start_clean_cycle(self) -> None:
        """
        Begin the cleaning cycle in a separate thread.
        """
        if self._clean_thread and self._clean_thread.is_alive():
            return  # already cleaning
        self._clean_stop.clear()
        self._clean_thread = threading.Thread(target=self._clean_loop, daemon=True)
        self._clean_thread.start()
        logging.info("Cleaning cycle started")

    def stop_clean_cycle(self) -> None:
        """
        Signal the cleaning cycle to stop, stop VFD, then close valves after delay.
        """
        self._clean_stop.set()
        # Immediately stop VFD
        self.vfd_state = self.vfd_stop_cmd
        self.vfd_speed = 0
        # Schedule valves closure after clean_stop_delay
        delay = self.config.get("clean_stop_delay")
        threading.Timer(delay, lambda: (
            self.modbus.set_valve("both", "close"),
            logging.info("Cleaning cycle stopped: valves closed")
        )).start()
        logging.info("Cleaning cycle stop initiated")


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
            self.modbus.set_vfd_state(self.vfd_stop_cmd)
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
            except NoResponseError as e:
                # Non‐fatal: instrument didn’t answer this cycle
                logging.debug(f"Modbus no response (will retry): {e}")
            except Exception:
                logging.exception("Error in modbus loop")
            time.sleep(self._read_interval)

    def _vfd_loop(self) -> None:
        """
        Poll VFD commands at its own interval.
        """
        while not self.kill_all.is_set():
            try:
                self.modbus.set_vfd_state(self.vfd_state)
                self.modbus.set_vfd_speed(self.vfd_speed)
            except NoResponseError as e:
                logging.debug(f"VFD no response: {e}")
            except Exception:
                logging.exception("Error in VFD loop")
            time.sleep(self._vfd_interval)

    def _valve_loop(self) -> None:
        """
        Poll valve states at their own interval.
        """
        while not self.kill_all.is_set():
            try:
                self.modbus.set_valve("left",  "open" if self.valve1 else "close")
                self.modbus.set_valve("right", "open" if self.valve2 else "close")
            except NoResponseError as e:
                logging.debug(f"Valve no response: {e}")
            except Exception:
                logging.exception("Error in valve loop")
            time.sleep(self._valve_interval)

    def _scale_loop(self) -> None:
        """
        Poll load cell at its own interval.
        """
        while not self.kill_all.is_set():
            try:
                self.actual_weight = self.modbus.read_load_cell()
            except NoResponseError as e:
                logging.debug(f"Scale no response: {e}")
            except Exception:
                logging.exception("Error in scale loop")
            time.sleep(self._scale_interval)

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

    def _clean_loop(self) -> None:
        """
        Internal cleaning cycle loop:
        - Open left valve, wait initial delay, start VFD at clean_speed
        - Alternate opening right/left valves every clean_interval with toggle delays
        """
        cfg = self.config
        # initial left-open and VFD start
        self.modbus.set_valve("left", "open")
        time.sleep(cfg.get("clean_initial_delay"))
        self.vfd_state = self.vfd_run_cmd
        self.vfd_speed = int(cfg.get("clean_speed") * 100)

        # alternate cycle
        left_open = True
        interval    = cfg.get("clean_interval")
        toggle_delay= cfg.get("clean_toggle_delay")

        while not self._clean_stop.is_set():
            time.sleep(interval)
            if left_open:
                self.modbus.set_valve("right", "open")
                time.sleep(toggle_delay)
                self.modbus.set_valve("left", "close")
            else:
                self.modbus.set_valve("left", "open")
                time.sleep(toggle_delay)
                self.modbus.set_valve("right", "close")
            left_open = not left_open

        logging.info("Exiting clean loop")

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
                            self._left_tare = w
                            self._mould_tare = w
                            self.valve1     = True
                            time.sleep(self._valve_delay)
                            self.vfd_state  = self.vfd_run_cmd
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
                        self.vfd_state = self.vfd_stop_cmd
                        time.sleep(self._post_fill_delay)
                        self.valve1 = False
                        time.sleep(self._post_fill_delay)
                        # Prepare right fill
                        self._state = self.STATE_PREP_RIGHT

                # 4) Prep right: open valve, start fast fill
                elif self._state == self.STATE_PREP_RIGHT:
                    self._consec_count = 0
                    self._right_tare = w
                    self._tare_weight  = w
                    self.valve2        = True
                    self.vfd_state     = self.vfd_run_cmd
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
                        self.vfd_state = self.vfd_stop_cmd
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