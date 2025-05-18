import minimalmodbus
import serial
import logging
import time

class ModbusInterface:
    """
    Wraps three Modbus devices on the same serial bus:
      - VFD (address 2, ASCII mode, 19200 baud, /dev/ttySC1)
      - Load cell (address 1, RTU mode, 9600 baud, /dev/ttySC0)
      - Valve controller (address 3, RTU mode, 9600 baud, /dev/ttySC0)
    """

    def __init__(self, config):
        # VFD (turny_boi)
        self.vfd = minimalmodbus.Instrument("/dev/ttySC1", 2, minimalmodbus.MODE_ASCII)
        #self.vfd.mode    = minimalmodbus.MODE_ASCII
        self.vfd.serial.baudrate = 19200
        self.vfd.serial.timeout  = 0.05
        self.vfd.serial.parity   = minimalmodbus.serial.PARITY_NONE
        self.vfd.serial.bytesize = 8
        self.vfd.serial.stopbits = 1
        self.vfd.clear_buffers_before_each_transaction = True
        self.vfd.close_port_after_each_call            = True

        # Load cell
        self.scale = minimalmodbus.Instrument("/dev/ttySC0", 1)
        self.scale.mode    = minimalmodbus.MODE_RTU
        self.scale.serial.baudrate = 9600
        self.scale.serial.timeout  = 0.5
        self.scale.serial.parity   = minimalmodbus.serial.PARITY_NONE
        self.scale.serial.bytesize = 8
        self.scale.serial.stopbits = 1
        self.scale.clear_buffers_before_each_transaction = True
        self.scale.close_port_after_each_call            = True

        # Valve controller
        self.valves = minimalmodbus.Instrument("/dev/ttySC0", 3)
        self.valves.mode    = minimalmodbus.MODE_RTU
        self.valves.serial.baudrate = 9600
        self.valves.serial.timeout  = 0.4
        self.valves.serial.parity   = minimalmodbus.serial.PARITY_NONE
        self.valves.serial.bytesize = 8
        self.valves.serial.stopbits = 1
        self.valves.clear_buffers_before_each_transaction = True
        self.valves.close_port_after_each_call            = True

        # Poll intervals (seconds) for each device
        self.vfd_interval   = config.get("vfd_poll_interval")
        self.scale_interval = config.get("scale_poll_interval")
        self.valve_interval = config.get("valve_poll_interval")

        # Track last poll times
        self._last_vfd_time   = time.time()
        self._last_scale_time = time.time()
        self._last_valve_time = time.time()

        # Ensure both valves are closed at startup
        try:
            self.set_valve("both", "close")
        except minimalmodbus.NoResponseError as e:
            logging.warning(f"Could not close valves at startup: {e}")
        except Exception as e:
            logging.warning(f"Unexpected error closing valves at startup: {e}")

        # Track current valve states for combined register writes
        self._valve1_state = 0
        self._valve2_state = 0

    def read_load_cell(self) -> float:
        now = time.time()
        elapsed = now - self._last_scale_time
        if elapsed < self.scale_interval:
            time.sleep(self.scale_interval - elapsed)
        self._last_scale_time = time.time()
        """
        Read a 32-bit signed value from the load cell and return kilograms.
        """
        raw = self.scale.read_long(0x0000, 3, False, 0)
        if raw > 0x7FFFFFFF:
            raw -= 0x100000000
        return raw / 1000.0

    def set_vfd_state(self, state: int):
        """
        Write to the VFD state register (e.g., 0=stop, 6=start).
        """
        now = time.time()
        elapsed = now - self._last_vfd_time
        if elapsed < self.vfd_interval:
            time.sleep(self.vfd_interval - elapsed)
        logging.info(f"ModbusInterface: sending VFD control command {state} to register 0x2000")
        # functioncode=6 (Write Single Register), decimals=0
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
        logging.info(f"ModbusInterface: setting VFD speed reference to {speed} (×100) at register 0x2001")
        # speed is already scaled: Hz × 100
        self.vfd.write_register(0x2001, speed, 0, functioncode=6)
        self._last_vfd_time = time.time()

    def set_valve(self, valve: str, action: str):
        now = time.time()
        elapsed = now - self._last_valve_time
        if elapsed < self.valve_interval:
            time.sleep(self.valve_interval - elapsed)
        """
        Control valves by aggregating into a single register write.
          valve: "left", "right", or "both"
          action: "open" or "close"
        """
        # Determine new individual valve states
        if valve == "both":
            new_left  = 1 if action == "open" else 0
            new_right = 1 if action == "open" else 0
        elif valve == "left":
            new_left  = 1 if action == "open" else 0
            new_right = self._valve2_state
        elif valve == "right":
            new_left  = self._valve1_state
            new_right = 1 if action == "open" else 0
        else:
            raise ValueError(f"Unknown valve: {valve}")

        # Update stored states
        self._valve1_state = new_left
        self._valve2_state = new_right

        # Compute combined value: bit0=left, bit1=right
        combined = new_left + (new_right << 1)

        # Write combined valve state to single register
        try:
            self.valves.write_register(0x0080, combined, 0, functioncode=6)
        except Exception:
            logging.exception(f"Valves MODBUS error - {combined}")
        # Update timestamp after successful write
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
            result['scale'] = self.read_load_cell()
            self._last_scale_time = now
        # VFD status register (0x2002)
        if now - self._last_vfd_time >= self.vfd_interval:
            result['vfd'] = self.vfd.read_register(0x2002, 0, functioncode=3)
            self._last_vfd_time = now
        # Valve coils
        if now - self._last_valve_time >= self.valve_interval:
            result['valves'] = {
                'left':  self.valves.read_bit(0, functioncode=1),
                'right': self.valves.read_bit(1, functioncode=1)
            }
            self._last_valve_time = now
        return result