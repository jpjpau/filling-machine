import minimalmodbus
import serial
import logging
import time
import threading
from collections import deque
import glob
import os

class ModbusInterface:
    """
    Wraps three Modbus devices on the same serial bus:
      - VFD (address 2, ASCII mode, 19200 baud, /dev/ttySC1)
      - Load cell (address 1, RTU mode, 9600 baud, /dev/ttySC0)
      - Valve controller (address 3, RTU mode, 9600 baud, /dev/ttySC0)
    Provides thread-safe access and polling mechanisms with rate limiting.
    """

    def __init__(self, config):
        logging.info("Initializing ModbusInterface with provided configuration.")

        # Static port selection for CH9344 USB adapter
        if os.path.exists("/dev/ttyCH9344USB0"):
            valve_port = "/dev/ttyCH9344USB0"
            scale_port = "/dev/ttyCH9344USB1"
            vfd_port   = "/dev/ttyCH9344USB2"
            logging.info("Detected CH9344 USB ports at /dev/ttyCH9344USB0..2")
        else:
            valve_port = "/dev/ttyCH9344USB8"
            scale_port = "/dev/ttyCH9344USB9"
            vfd_port   = "/dev/ttyCH9344USB10"
            logging.info("Using fallback CH9344 USB ports at /dev/ttyCH9344USB8..10")

        # Initialize VFD instrument (ASCII mode)
        self.vfd = minimalmodbus.Instrument(vfd_port, 2, minimalmodbus.MODE_ASCII)
        self.vfd.serial.baudrate = 19200
        self.vfd.serial.timeout  = 0.05
        self.vfd.serial.parity   = minimalmodbus.serial.PARITY_NONE
        self.vfd.serial.bytesize = 8
        self.vfd.serial.stopbits = 1
        self.vfd.clear_buffers_before_each_transaction = True
        self.vfd.close_port_after_each_call            = False
        logging.debug(f"Configured VFD on port {vfd_port} with ASCII mode, 19200 baud.")

        # Initialize Load cell instrument (RTU mode)
        self.scale = minimalmodbus.Instrument(scale_port, 1)
        self.scale.mode    = minimalmodbus.MODE_RTU
        self.scale.serial.baudrate = 9600
        self.scale.serial.timeout  = 0.05
        self.scale.serial.parity   = minimalmodbus.serial.PARITY_NONE
        self.scale.serial.bytesize = 8
        self.scale.serial.stopbits = 1
        self.scale.clear_buffers_before_each_transaction = True
        self.scale.close_port_after_each_call            = False
        logging.debug(f"Configured Load cell on port {scale_port} with RTU mode, 9600 baud.")

        # Initialize Valve controller instrument (RTU mode)
        self.valves = minimalmodbus.Instrument(valve_port, 1)
        self.valves.mode    = minimalmodbus.MODE_RTU
        self.valves.serial.baudrate = 9600
        self.valves.serial.timeout  = 0.05
        self.valves.serial.parity   = minimalmodbus.serial.PARITY_NONE
        self.valves.serial.bytesize = 8
        self.valves.serial.stopbits = 1
        self.valves.clear_buffers_before_each_transaction = True
        self.valves.close_port_after_each_call            = False
        logging.debug(f"Configured Valve controller on port {valve_port} with RTU mode, 9600 baud.")

        # Poll intervals (seconds) for each device, fetched from config dict
        self.vfd_interval   = config.get("vfd_poll_interval")
        self.scale_interval = config.get("scale_poll_interval")
        self.valve_interval = config.get("valve_poll_interval")
        logging.info(f"Polling intervals set - VFD: {self.vfd_interval}s, Scale: {self.scale_interval}s, Valve: {self.valve_interval}s")

        # Track last poll times to enforce minimum polling intervals
        self._last_vfd_time   = time.time()
        self._last_scale_time = time.time()
        self._last_valve_time = time.time()

        # History of recent load-cell readings for smoothing, maxlen=5
        self._scale_history = deque(maxlen=5)
        logging.debug("Initialized load cell reading history buffer.")

        # Locks to prevent concurrent access to shared resources
        self._vfd_lock = threading.Lock()
        self._valve_lock = threading.Lock()
        self._scale_lock = threading.Lock()
        logging.debug("Threading locks initialized for VFD, valves, and scale.")

        # Track current valve states for combined register writes if needed
        self._valve1_state = 0
        self._valve2_state = 0
        logging.debug("Valve states initialized to closed (0).")

    def read_load_cell(self) -> float:
        """
        Read the current load-cell value, smoothed over recent readings.
        Enforces minimum interval between reads to avoid bus flooding.
        Returns:
            float: Smoothed load-cell weight in kilograms.
        """
        now     = time.time()
        elapsed = now - self._last_scale_time
        logging.debug(f"Attempting to read load cell; {elapsed:.3f}s since last read.")
        if elapsed < self.scale_interval:
            sleep_time = self.scale_interval - elapsed
            logging.debug(f"Sleeping for {sleep_time:.3f}s to enforce scale poll interval.")
            time.sleep(sleep_time)

        with self._scale_lock:
            try:
                raw = self.scale.read_long(0x0000, 3, False, 0)
                logging.debug(f"Raw load cell reading: {raw}")
            except Exception as e:
                logging.error(f"Exception during load cell read: {e}", exc_info=True)
                raise

        # Convert 32-bit signed integer from unsigned if necessary
        if raw > 0x7FFFFFFF:
            raw -= 0x100000000
            logging.debug(f"Converted raw load cell value to signed: {raw}")

        # Convert raw value to kilograms (assuming scale factor 1000)
        weight = raw / 1000.0
        logging.debug(f"Converted load cell reading to kg: {weight:.3f}")

        # Add to history for smoothing
        self._scale_history.append(weight)
        avg_weight = sum(self._scale_history) / len(self._scale_history)
        logging.debug(f"Smoothed load cell weight over last {len(self._scale_history)} readings: {avg_weight:.3f} kg")

        # Update timestamp after successful read
        self._last_scale_time = time.time()
        logging.info(f"Load cell reading updated at {self._last_scale_time}")
        return avg_weight

    def set_vfd_state(self, state: int):
        """
        Write to the VFD state register to control operation (e.g., 0=stop, 6=start).
        Enforces minimum interval between writes to prevent bus flooding.
        Args:
            state (int): Desired VFD state code.
        """
        now = time.time()
        elapsed = now - self._last_vfd_time
        logging.debug(f"Setting VFD state to {state}; {elapsed:.3f}s since last VFD command.")
        if elapsed < self.vfd_interval:
            sleep_time = self.vfd_interval - elapsed
            logging.debug(f"Sleeping for {sleep_time:.3f}s to enforce VFD poll interval.")
            time.sleep(sleep_time)

        with self._vfd_lock:
            try:
                logging.info(f"Sending VFD control command {state} to register 0x2000")
                self.vfd.write_register(0x2000, state, 0, functioncode=6)
                self._last_vfd_time = time.time()
                logging.info(f"VFD state set successfully at {self._last_vfd_time}")
            except Exception as e:
                logging.error(f"Failed to set VFD state {state}: {e}", exc_info=True)
                raise

    def set_vfd_speed(self, speed: int):
        """
        Write to the VFD speed register.
        `speed` should already be scaled appropriately (e.g., Hz × 100).
        Enforces minimum interval between writes.
        Args:
            speed (int): Speed reference value.
        """
        now = time.time()
        elapsed = now - self._last_vfd_time
        logging.debug(f"Setting VFD speed to {speed}; {elapsed:.3f}s since last VFD command.")
        if elapsed < self.vfd_interval:
            sleep_time = self.vfd_interval - elapsed
            logging.debug(f"Sleeping for {sleep_time:.3f}s to enforce VFD poll interval.")
            time.sleep(sleep_time)

        with self._vfd_lock:
            try:
                logging.info(f"Setting VFD speed reference to {speed} (×100) at register 0x2001")
                self.vfd.write_register(0x2001, speed, 0, functioncode=6)
                self._last_vfd_time = time.time()
                logging.info(f"VFD speed set successfully at {self._last_vfd_time}")
            except Exception as e:
                logging.error(f"Failed to set VFD speed {speed}: {e}", exc_info=True)
                raise

    def set_valve(self, valve: str, action: str):
        """
        Open or close specified valve(s).
        Enforces minimum interval between writes and serializes access.
        Args:
            valve (str): 'left', 'right', or 'both'
            action (str): 'open' or 'close'
        Raises:
            ValueError: if valve or action is unknown.
        """
        now     = time.time()
        elapsed = now - self._last_valve_time
        logging.debug(f"Setting valve(s) '{valve}' to '{action}'; {elapsed:.3f}s since last valve command.")
        if elapsed < self.valve_interval:
            sleep_time = self.valve_interval - elapsed
            logging.debug(f"Sleeping for {sleep_time:.3f}s to enforce valve poll interval.")
            time.sleep(sleep_time)

        with self._valve_lock:
            mapping = {"left": 0, "right": 1}
            if valve == "both":
                coils = list(mapping.values())
                logging.debug("Targeting both valves.")
            elif valve in mapping:
                coils = [mapping[valve]]
                logging.debug(f"Targeting valve '{valve}' at coil {coils[0]}.")
            else:
                logging.error(f"Unknown valve specified: {valve}")
                raise ValueError(f"Unknown valve: {valve}")

            if action == "open":
                bit = True
                logging.debug("Action is to open valve(s).")
            elif action == "close":
                bit = False
                logging.debug("Action is to close valve(s).")
            else:
                logging.error(f"Unknown action specified: {action}")
                raise ValueError(f"Unknown action: {action}")

            for coil in coils:
                try:
                    logging.info(f"Writing coil {coil} to {'ON' if bit else 'OFF'} (function code 5)")
                    self.valves.write_bit(coil, bit)
                    logging.info(f"Valve coil {coil} set successfully.")
                except Exception as e:
                    logging.error(f"Valves MODBUS error on coil {coil} action {action}: {e}", exc_info=True)

        self._last_valve_time = time.time()
        logging.info(f"Valve command completed at {self._last_valve_time}")

    def poll(self):
        """
        Poll each Modbus device when its configured interval elapses.
        Returns a dict with keys for whichever device(s) were polled:
          - 'scale': latest load-cell reading (kg)
          - 'vfd':   latest VFD status word
          - 'valves': {'left': bit0, 'right': bit1}
        Returns:
            dict: Polled data from devices.
        """
        now = time.time()
        result = {}

        # Poll scale if interval elapsed
        if now - self._last_scale_time >= self.scale_interval:
            logging.debug("Polling load cell due to interval elapsed.")
            try:
                result['scale'] = self.read_load_cell()
                self._last_scale_time = now
                logging.info(f"Load cell polled successfully: {result['scale']:.3f} kg")
            except Exception:
                logging.exception("Error polling scale")

        # Poll VFD status register (0x2002) if interval elapsed
        if now - self._last_vfd_time >= self.vfd_interval:
            logging.debug("Polling VFD status due to interval elapsed.")
            try:
                vfd_status = self.vfd.read_register(0x2002, 0, functioncode=3)
                result['vfd'] = vfd_status
                self._last_vfd_time = now
                logging.info(f"VFD status polled successfully: {vfd_status}")
            except Exception:
                logging.exception("Error polling VFD")

        # Poll valve coils if interval elapsed
        if now - self._last_valve_time >= self.valve_interval:
            logging.debug("Polling valves due to interval elapsed.")
            try:
                valves_state = {
                    'left':  self.valves.read_bit(0, functioncode=1),
                    'right': self.valves.read_bit(1, functioncode=1)
                }
                result['valves'] = valves_state
                self._last_valve_time = now
                logging.info(f"Valve states polled successfully: {valves_state}")
            except Exception:
                logging.exception("Error polling valves")

        return result