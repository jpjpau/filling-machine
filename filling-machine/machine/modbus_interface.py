import minimalmodbus
import serial
import logging
import time
import threading
from collections import deque

class ModbusInterface:
    """
    Wraps three Modbus devices on the same serial bus:
      - VFD (address 2, ASCII mode, 19200 baud, /dev/ttySC1)
      - Load cell (address 1, RTU mode, 9600 baud, /dev/ttySC0)
      - Valve controller (address 3, RTU mode, 9600 baud, /dev/ttySC0)
    """

    def __init__(self, config):
        # VFD (turny_boi)
        self.vfd = minimalmodbus.Instrument("/dev/ttyCH9344USB10", 2, minimalmodbus.MODE_ASCII)
        #self.vfd.mode    = minimalmodbus.MODE_ASCII
        self.vfd.serial.baudrate = 19200
        self.vfd.serial.timeout  = 0.05
        self.vfd.serial.parity   = minimalmodbus.serial.PARITY_NONE
        self.vfd.serial.bytesize = 8
        self.vfd.serial.stopbits = 1
        self.vfd.clear_buffers_before_each_transaction = True
        self.vfd.close_port_after_each_call            = False


        # Load cell
        self.scale = minimalmodbus.Instrument("/dev/ttyCH9344USB9", 1)
        self.scale.mode    = minimalmodbus.MODE_RTU
        self.scale.serial.baudrate = 9600
        self.scale.serial.timeout  = 0.05
        self.scale.serial.parity   = minimalmodbus.serial.PARITY_NONE
        self.scale.serial.bytesize = 8
        self.scale.serial.stopbits = 1
        self.scale.clear_buffers_before_each_transaction = True
        self.scale.close_port_after_each_call            = False

        # Valve controller
        self.valves = minimalmodbus.Instrument("/dev/ttyCH9344USB8", 1)
        self.valves.mode    = minimalmodbus.MODE_RTU
        self.valves.serial.baudrate = 9600
        self.valves.serial.timeout  = 0.05
        self.valves.serial.parity   = minimalmodbus.serial.PARITY_NONE
        self.valves.serial.bytesize = 8
        self.valves.serial.stopbits = 1
        self.valves.clear_buffers_before_each_transaction = True
        self.valves.close_port_after_each_call            = False

        # Poll intervals (seconds) for each device
        self.vfd_interval   = config.get("vfd_poll_interval")
        self.scale_interval = config.get("scale_poll_interval")
        self.valve_interval = config.get("valve_poll_interval")

        # Track last poll times
        self._last_vfd_time   = time.time()
        self._last_scale_time = time.time()
        self._last_valve_time = time.time()
        # history of recent load-cell readings for smoothing
        self._scale_history = deque(maxlen=5)
        
        # Prevent concurrent access to VFD and valves
        self._vfd_lock = threading.Lock()
        self._valve_lock = threading.Lock()

        # Lock to serialize valve register writes
        self._valve_lock   = threading.Lock()
        # Lock to serialize scale reads
        self._scale_lock = threading.Lock()
        # Track current valve states for combined register writes
        self._valve1_state = 0
        self._valve2_state = 0

    def read_load_cell(self) -> float:
        """
        Read the current load-cell value, smoothed over recent readings.
        """
        now     = time.time()
        elapsed = now - self._last_scale_time
        if elapsed < self.scale_interval:
            time.sleep(self.scale_interval - elapsed)

        # serialize access to the scale
        # with self._scale_lock:
        #     raw = self.scale.read_long(0x0000, 3, False, 0)
        raw = self.scale.read_long(0x0000, 3, False, 0)
        if raw > 0x7FFFFFFF:
            raw -= 0x100000000

        # convert raw value to kilograms
        weight = raw / 1000.0
        # add to history for smoothing
        self._scale_history.append(weight)
        # compute average of recent readings
        avg_weight = sum(self._scale_history) / len(self._scale_history)

        # update timestamp after read
        self._last_scale_time = time.time()
        return avg_weight

    def set_vfd_state(self, state: int):
        """
        Write to the VFD state register (e.g., 0=stop, 6=start).
        """
        now = time.time()
        elapsed = now - self._last_vfd_time
        if elapsed < self.vfd_interval:
            time.sleep(self.vfd_interval - elapsed)

        with self._vfd_lock:
            logging.info(f"ModbusInterface: sending VFD control command {state} to register 0x2000")
            self.vfd.write_register(0x2000, state, 0, functioncode=6)
            self._last_vfd_time = time.time()

    def set_vfd_speed(self, speed: int):
        """
        Write to the VFD speed register (0–255).
        `speed` should already be scaled (e.g., Hz × 100).
        """
        now = time.time()
        elapsed = now - self._last_vfd_time
        if elapsed < self.vfd_interval:
            time.sleep(self.vfd_interval - elapsed)

        with self._vfd_lock:
            logging.info(f"ModbusInterface: setting VFD speed reference to {speed} (×100) at register 0x2001")
            self.vfd.write_register(0x2001, speed, 0, functioncode=6)
            self._last_vfd_time = time.time()

    def set_valve(self, valve: str, action: str):
        # Enforce minimum interval between writes
        now     = time.time()
        elapsed = now - self._last_valve_time
        if elapsed < self.valve_interval:
            time.sleep(self.valve_interval - elapsed)

        # Serialize access so no two threads write at once
        with self._valve_lock:
            # map valve names to coil indices
            mapping = {"left": 0, "right": 1}
            if valve == "both":
                coils = list(mapping.values())
            elif valve in mapping:
                coils = [mapping[valve]]
            else:
                raise ValueError(f"Unknown valve: {valve}")

            # determine bit value
            if action == "open":
                bit = True
            elif action == "close":
                bit = False
            else:
                raise ValueError(f"Unknown action: {action}")

            # write each coil separately
            for coil in coils:
                try:
                    # functioncode=5 (Write Single Coil)
                    self.valves.write_bit(coil, bit)
                except Exception:
                    logging.exception(f"Valves MODBUS error on coil {coil} action {action}")
        # update timestamp once we've finished
        self._last_valve_time = time.time()
    def poll(self):
        """
        Poll each Modbus device when its configured interval elapses.
        Returns a dict with keys for whichever device(s) were polled:
          - 'scale': latest load-cell reading (kg)
          - 'vfd':   latest VFD status word
          - 'valves': {'left': bit0, 'right': bit1}
        """
        now = time.time()
        result = {}
        # Scale (load cell)
        if now - self._last_scale_time >= self.scale_interval:
            try:
                result['scale'] = self.read_load_cell()
                self._last_scale_time = now
            except Exception:
                logging.exception("Error polling scale")        # VFD status register (0x2002)
        if now - self._last_vfd_time >= self.vfd_interval:
            try:
                result['vfd'] = self.vfd.read_register(0x2002, 0, functioncode=3)
                self._last_vfd_time = now
            except Exception:
                logging.exception("Error polling VFD")        # Valve coils
        if now - self._last_valve_time >= self.valve_interval:
            try:
                result['valves'] = {
                    'left':  self.valves.read_bit(0, functioncode=1),
                    'right': self.valves.read_bit(1, functioncode=1)
                }
                self._last_valve_time = now
            except Exception:
                logging.exception("Error polling valves")
                return result