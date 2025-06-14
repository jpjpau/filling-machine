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

import gpiod

chip = gpiod.Chip('gpiochip0')
left_button_line = chip.get_line(17)
right_button_line = chip.get_line(18)

left_button_line.request(consumer="left_button", type=gpiod.LINE_REQ_DIR_IN, flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP)
right_button_line.request(consumer="right_button", type=gpiod.LINE_REQ_DIR_IN, flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_UP)

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
        self._read_interval    = config.get("controller_interval")    # e.g. 0.1s
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
        # Cleaning speed (Hz), configurable via UI and config.json
        self.clean_speed       = config.get("clean_speed")

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
        self._cleaning_active = False

        # Pour tracking
        self._left_tare = None
        self._right_tare = None
        self._mould_tare = None  # the weight when tray + moulds first detected
        # Pour retention
        self._last_left_pour = 0.0
        self._last_right_pour = 0.0

        # Fill activation event, only start filling when UI Fill tab selected
        self._filling_event = threading.Event()
        
        # Manual top-up button state
        self._left_button_active = False
        self._right_button_active = False
        
        # --- WATCHDOG SETUP ---
        # how often we check (seconds) and how long before we consider a thread dead
        self.watchdog_interval  = self.config.get("watchdog_interval")
        self.watchdog_threshold = self.config.get("watchdog_threshold")

        # store last “beat” timestamp per thread
        self._last_heartbeat = {
            "modbus_vfd": time.time(),
            "modbus_valve": time.time(),
            "modbus_scale": time.time(),
        }
        self.watchdog_ok = True

        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True
        )
        self._watchdog_thread.start()

    def select_flavour(self, name: str) -> None:
        """
        Change target volume and mould weight based on flavour.
        """
        self.desired_volume = self.config.get(name)
        # Update mould weight from nested mould_weights
        self.mould_weight   = self.config.mould_weights.get(name)
        logging.info(f"Flavour selected: {name}, volume={self.desired_volume}, mould={self.mould_weight}")

    def enable_filling(self) -> None:
        """Allow filling loop to start after UI Fill tab selected."""
        self._filling_event.set()

    @property
    def current_left_pour(self) -> float:
        """
        How much has been poured into the left mould so far.
        Retained after fill until tray removal.
        """
        # During left fill phases, compute live pour
        if self._left_tare is not None and self._state in (self.STATE_FILL_LEFT_FAST, self.STATE_FILL_LEFT_SLOW):
            poured = self.actual_weight - self._left_tare
            return max(0.0, min(self.desired_volume, poured))
        # Otherwise, use last recorded pour
        return self._last_left_pour

    @property
    def current_right_pour(self) -> float:
        """
        How much has been poured into the right mould so far.
        Retained after fill until tray removal.
        """
        # During right fill phases, compute live pour
        if self._right_tare is not None and self._state in (self.STATE_FILL_RIGHT_FAST, self.STATE_FILL_RIGHT_SLOW):
            poured = self.actual_weight - self._right_tare
            return max(0.0, min(self.desired_volume, poured))
        # Otherwise, use last recorded pour
        return self._last_right_pour

    @property
    def mould_tare_weight(self) -> float:
        """Weight of tray + moulds when first placed (before filling)."""
        return 0.0 if self._mould_tare is None else self._mould_tare

    def start_manual_topup(self, side: str, initiated_by_ui: bool = False):
        if side == "left":
            if initiated_by_ui or not self._left_button_active:
                logging.info(f"Manual LEFT top-up activated ({'UI' if initiated_by_ui else 'Button'}).")
                self._left_button_active = True
                self.valve1 = True
                self.vfd_state = self.vfd_run_cmd
                self.vfd_speed = int(self.speed_slow * 100)
        elif side == "right":
            if initiated_by_ui or not self._right_button_active:
                logging.info(f"Manual RIGHT top-up activated ({'UI' if initiated_by_ui else 'Button'}).")
                self._right_button_active = True
                self.valve2 = True
                self.vfd_state = self.vfd_run_cmd
                self.vfd_speed = int(self.speed_slow * 100)

    def stop_manual_topup(self, side: str, initiated_by_ui: bool = False):
        if side == "left":
            if initiated_by_ui or self._left_button_active:
                logging.info(f"Manual LEFT top-up deactivated ({'UI' if initiated_by_ui else 'Button'}).")
                self.valve1 = False
                self._left_button_active = False
        elif side == "right":
            if initiated_by_ui or self._right_button_active:
                logging.info(f"Manual RIGHT top-up deactivated ({'UI' if initiated_by_ui else 'Button'}).")
                self.valve2 = False
                self._right_button_active = False

        # Only stop VFD if both buttons inactive
        if not self._left_button_active and not self._right_button_active:
            self.vfd_state = self.vfd_stop_cmd
            self.vfd_speed = 0
            
    def handle_left_button(self):
        button_pressed = not left_button_line.get_value()
        manual_states = [self.STATE_WAITING_FOR_MOULD, self.STATE_WAIT_REMOVAL]
        # Log the button state and internal state for debugging
        log_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        logging.debug(
            f"[{log_time}] [GPIO] LEFT button raw value={left_button_line.get_value()} | interpreted_pressed={button_pressed} | "
            f"_left_button_active={self._left_button_active} | state={self._state}"
        )
        if button_pressed and self._state in manual_states:
            # Only start if not already active from button (ignore if UI started)
            if not self._left_button_active:
                logging.info(
                    f"[{log_time}] [GPIO] LEFT button PRESSED: activating manual top-up. _left_button_active={self._left_button_active}, state={self._state}"
                )
                self._left_button_active = True
                self.start_manual_topup("left")
        else:
            # Only stop if we previously started from button (not if UI started)
            if self._left_button_active:
                logging.info(
                    f"[{log_time}] [GPIO] LEFT button RELEASED: deactivating manual top-up. _left_button_active={self._left_button_active}, state={self._state}"
                )
                self.stop_manual_topup("left")
                self._left_button_active = False

    def handle_right_button(self):
        button_pressed = not right_button_line.get_value()
        manual_states = [self.STATE_WAITING_FOR_MOULD, self.STATE_WAIT_REMOVAL]
        # Log the button state and internal state for debugging
        log_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        logging.debug(
            f"[{log_time}] [GPIO] RIGHT button raw value={right_button_line.get_value()} | interpreted_pressed={button_pressed} | "
            f"_right_button_active={self._right_button_active} | state={self._state}"
        )
        if button_pressed and self._state in manual_states:
            # Only start if not already active from button (ignore if UI started)
            if not self._right_button_active:
                logging.info(
                    f"[{log_time}] [GPIO] RIGHT button PRESSED: activating manual top-up. _right_button_active={self._right_button_active}, state={self._state}"
                )
                self._right_button_active = True
                self.start_manual_topup("right")
        else:
            # Only stop if we previously started from button (not if UI started)
            if self._right_button_active:
                logging.info(
                    f"[{log_time}] [GPIO] RIGHT button RELEASED: deactivating manual top-up. _right_button_active={self._right_button_active}, state={self._state}"
                )
                self.stop_manual_topup("right")
                self._right_button_active = False

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
        def close_valves():
            self.valve1 = False
            self.valve2 = False
            logging.info("Cleaning cycle stopped: valves closed")
        threading.Timer(delay, close_valves).start()

        logging.info("Cleaning cycle stop initiated")


    def stop(self) -> None:
        """
        Signal threads to stop and wait for them. Ensure clean shutdown.
        """
        
        # Hardware shutdown (set class attributes only; Modbus threads handle hardware)
        self.vfd_speed = 0
        self.vfd_state = self.vfd_stop_cmd
        self.valve1 = False
        self.valve2 = False
        
        # Ensure the filling loop unblocks if waiting for UI
        self._filling_event.set()
        self.kill_all.set()
        for t in self._threads:
            t.join()
        time.sleep(1)  # allow time for threads to exit

        # Always disconnect MQTT
        try:
            self.mqtt.disconnect()
        except Exception:
            logging.exception("Error during MQTT shutdown")

        logging.info("MachineController: stopped")

    def _feed_watchdog(self, name:str):
        self._last_heartbeat[name] = time.time()
        
    def _watchdog_loop(self):
        """Periodically check that each thread has called _feed_watchdog recently."""
        while not self.kill_all.is_set():
            now = time.time()
            all_good = True
            for name, ts in self._last_heartbeat.items():
                if now - ts > self.watchdog_threshold:
                    logging.error(f"Watchdog: {name} thread unresponsive!")
                    all_good = False
            if all_good and not self.watchdog_ok:
                logging.info("Watchdog: all threads healthy again.")
            self.watchdog_ok = all_good
            time.sleep(self.watchdog_interval)

    def _vfd_loop(self) -> None:
        """
        Poll VFD commands at its own interval.
        """
        while not self.kill_all.is_set():
            try:
                self.modbus.set_vfd_state(self.vfd_state)
                self.modbus.set_vfd_speed(self.vfd_speed)
                self._feed_watchdog("modbus_vfd")
                if int(time.time() * 10) % 5 == 0:  # Every 0.5 seconds
                    logging.debug(f"VFD loop heartbeat: {self._last_heartbeat['modbus_vfd']}")
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
                self._feed_watchdog("modbus_valve")
                if int(time.time() * 10) % 5 == 0:
                    logging.debug(f"Valve loop heartbeat: {self._last_heartbeat['modbus_valve']}")
                print(f"Valve1: {self.valve1}, Valve2: {self.valve2}")
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
                self._feed_watchdog("modbus_scale")
                if int(time.time() * 10) % 5 == 0:
                    logging.debug(f"Scale loop heartbeat: {self._last_heartbeat['modbus_scale']}")
            except NoResponseError as e:
                logging.debug(f"Scale no response: {e}")
            except Exception:
                logging.exception("Error in scale loop")
            # time.sleep(self._scale_interval)

    def _monitor_loop(self) -> None:
        """
        Publish telemetry over MQTT.
        """
        while not self.kill_all.is_set():
            try:
                logging.debug(f"Telemetry: weight={self.actual_weight}, VFD={self.vfd_state}@{self.vfd_speed}, valve1={self.valve1}, valve2={self.valve2}, status={self.filling_status}")
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
        logging.debug(f"Detect mould check: actual={w}, target={self.mould_weight}, tol={self._mould_tol}")
        # Check if within mould tolerance
        return abs(w - self.mould_weight) <= self.mould_weight * self._mould_tol

    def _clean_loop(self) -> None:
        """
        Internal cleaning cycle loop:
        - Open left valve, wait initial delay, start VFD at clean_speed
        - Alternate opening right/left valves every clean_interval with toggle delays
        """
        self._cleaning_active = True
        cfg = self.config
        # initial left-open and VFD start
        self.valve1 = True
        time.sleep(cfg.get("clean_initial_delay"))
        self.clean_speed = self.config.get("clean_speed")
        self.vfd_state = self.vfd_run_cmd
        self.vfd_speed = int(self.clean_speed * 100)

        # alternate cycle
        left_open = True
        interval    = cfg.get("clean_interval")
        toggle_delay= cfg.get("clean_toggle_delay")

        while not self._clean_stop.is_set():
            # Inside the loop, to handle dynamic speed changes
            self.clean_speed = self.config.get("clean_speed")
            # Always use refreshed self.clean_speed for VFD speed
            self.vfd_speed = int(self.clean_speed * 100)
            if left_open:
                self.valve2 = True
                time.sleep(toggle_delay)
                self.valve1 = False
            else:
                self.valve1 = True
                time.sleep(toggle_delay)
                self.valve2 = False
            left_open = not left_open
            time.sleep(interval)

        logging.info("Exiting clean loop")
        self._cleaning_active = False

    def _filling_loop(self) -> None:
        """
        Full multi-stage fill state machine.
        """
        # Wait until UI triggers filling
        self._filling_event.wait()
        while not self.kill_all.is_set():
            # Prevent filling logic if cleaning is active
            if self._cleaning_active:
                time.sleep(self._read_interval)
                continue  # Skip filling state machine updates
            
            try:
                self.handle_left_button()
                self.handle_right_button()
                # even when I'm holding down the button, occassionally the VFD is told to stop by something.
                
                w = self.actual_weight

                # 1) Waiting until a mould tray is placed
                if self._state == self.STATE_WAITING_FOR_MOULD:
                    logging.debug(f"Entering state: {self._state}, weight={w}")
                    if abs(w - self.mould_weight) <= self.mould_weight * self._mould_tol:
                        self._consec_count = 1
                        self._state = self.STATE_CONFIRMING_MOULD

                # 1.1) Confirm consecutive mould readings
                elif self._state == self.STATE_CONFIRMING_MOULD:
                    logging.debug(f"Entering state: {self._state}, weight={w}")
                    if abs(w - self.mould_weight) <= self.mould_weight * self._mould_tol:
                        self._consec_count += 1
                        if self._consec_count >= self._confirm_readings:
                            # Delay before starting fill to allow user to adjust moulds
                            delay = self.config.get("mould_adjust_delay")
                            logging.info(f"Mould confirmed; waiting {delay} seconds for user adjustment before taring and filling")
                            time.sleep(delay)
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
                    logging.debug(f"Entering state: {self._state}, weight={w}")
                    self.vfd_speed = int(self.speed_fast * 100)
                    if (w - self._tare_weight) >= self.desired_volume * (1 - self._fill_tol):
                        self.vfd_speed = int(self.speed_slow * 100)
                        self._state    = self.STATE_FILL_LEFT_SLOW

                # 3) Slow-fill left until target reached
                elif self._state == self.STATE_FILL_LEFT_SLOW:
                    logging.debug(f"Entering state: {self._state}, weight={w}")
                    self.vfd_speed = int(self.speed_slow * 100)
                    if (w - self._tare_weight) >= self.desired_volume:
                        # Stop VFD and close left valve immediately
                        self.vfd_speed = 0
                        self.vfd_state = self.vfd_stop_cmd
                        time.sleep(self._post_fill_delay)
                        self.valve1 = False
                        time.sleep(self._post_fill_delay)

                        # Allow scale readings to settle and average a few samples
                        sample_count = 5
                        readings = []
                        for _ in range(sample_count):
                            time.sleep(self._scale_interval)
                            readings.append(self.actual_weight - self._left_tare)
                        avg_pour = sum(readings) / len(readings)
                        # Record the raw averaged pour amount (allowing overshoot to be visible)
                        self._last_left_pour = avg_pour

                        # Post-fill delay before moving to next stage
                        self._state = self.STATE_PREP_RIGHT

                # 4) Prep right: open valve, start fast fill
                elif self._state == self.STATE_PREP_RIGHT:
                    logging.debug(f"Entering state: {self._state}, weight={w}")
                    self._consec_count = 0
                    self._right_tare = w
                    self._tare_weight  = w
                    self.valve2        = True
                    self.vfd_state     = self.vfd_run_cmd
                    self.vfd_speed     = int(self.speed_fast * 100)
                    self._state        = self.STATE_FILL_RIGHT_FAST

                # 5) Fast-fill right
                elif self._state == self.STATE_FILL_RIGHT_FAST:
                    logging.debug(f"Entering state: {self._state}, weight={w}")
                    self.vfd_speed = int(self.speed_fast * 100)
                    if (w - self._tare_weight) >= self.desired_volume * (1 - self._fill_tol):
                        self.vfd_speed = int(self.speed_slow * 100)
                        self._state    = self.STATE_FILL_RIGHT_SLOW

                # 6) Slow-fill right until done
                elif self._state == self.STATE_FILL_RIGHT_SLOW:
                    logging.debug(f"Entering state: {self._state}, weight={w}")
                    self.vfd_speed = int(self.speed_slow * 100)
                    if (w - self._tare_weight) >= self.desired_volume:
                        # Stop VFD and close right valve immediately
                        self.vfd_speed = 0
                        self.vfd_state = self.vfd_stop_cmd
                        time.sleep(self._post_fill_delay)
                        self.valve2 = False
                        time.sleep(self._post_fill_delay)

                        # Allow scale readings to settle and average a few samples
                        sample_count = 5
                        readings = []
                        for _ in range(sample_count):
                            time.sleep(self._scale_interval)
                            readings.append(self.actual_weight - self._right_tare)
                        avg_pour = sum(readings) / len(readings)
                        # Record the raw averaged pour amount (allowing overshoot to be visible)
                        self._last_right_pour = avg_pour

                        # Post-fill delay before moving to wait removal stage
                        time.sleep(self._post_fill_delay)
                        self._state = self.STATE_WAIT_REMOVAL
                        self._consec_count = 0

                # 7) Wait for tray removal (multiple zero readings)
                elif self._state == self.STATE_WAIT_REMOVAL:
                    logging.debug(f"Entering state: {self._state}, weight={w}")
                    if w <= self._removal_tol:
                        self._consec_count += 1
                        if self._consec_count >= self._confirm_removals:
                            # Clear retained pour and tare data
                            self._last_left_pour  = 0.0
                            self._last_right_pour = 0.0
                            self._left_tare       = None
                            self._right_tare      = None
                            self._mould_tare      = None
                            # Re-tare for next cycle
                            self._tare_weight = w
                            self._state       = self.STATE_WAITING_FOR_MOULD
                    else:
                        self._consec_count = 0

            except Exception:
                logging.exception("Error in filling loop")

            time.sleep(self._read_interval)