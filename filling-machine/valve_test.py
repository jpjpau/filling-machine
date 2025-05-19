#!/usr/bin/env python3
import minimalmodbus
import serial
import time
import logging
import subprocess

# WAVESHARE Modbus RTU 8-ch Relay V3 – Channel mapping:
#  Relay 1 → coil address 0x0000 (instrument.write_bit(0,...))
#  Relay 2 → coil address 0x0001 (instrument.write_bit(1,...))
#  Use Function Code 05 (Write Single Coil): 0xFF00 = ON, 0x0000 = OFF

# Optional: enable debug logging from minimalmodbus
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    # Kill any process holding the serial port
    try:
        subprocess.run(["fuser", "-k", "/dev/ttyCH9344USB0"], check=True)
        logger.info("Killed processes using /dev/ttyCH9344USB0")
    except Exception as e:
        logger.warning(f"Failed to kill processes using /dev/ttyCH9344USB0: {e}")
    # Configure the valve controller instrument
    time.sleep(1)  # Wait for the serial port to be released
    instrument = minimalmodbus.Instrument("/dev/ttyCH9344USB0", 1)  # port, slave address
    instrument.mode = minimalmodbus.MODE_RTU
    instrument.serial.baudrate = 9600
    instrument.serial.timeout = 0.05
    instrument.serial.parity = serial.PARITY_NONE
    instrument.serial.bytesize = 8
    instrument.serial.stopbits = 1
    # Ensure serial buffers are cleared before each transaction if supported
    if hasattr(instrument, 'clear_buffers_before_each_transaction'):
        instrument.clear_buffers_before_each_transaction = False
    # Keep the serial port open for consecutive write_bit calls
    instrument.close_port_after_each_call = False

    # Enable debug logging for minimalmodbus
    instrument.debug = True
    mm_logger = logging.getLogger("minimalmodbus")
    mm_logger.setLevel(logging.DEBUG)
    mm_logger.addHandler(logging.StreamHandler())

    # Monkey-patch to log raw TX bytes in hex
    _orig_communicate = instrument._communicate
    def _logging_communicate(request_bytes, number_of_bytes_to_read):
        hex_str = ' '.join(f"{b:02X}" for b in request_bytes)
        logger.info(f"MinimalModbus TX: {hex_str}")
        return _orig_communicate(request_bytes, number_of_bytes_to_read)
    instrument._communicate = _logging_communicate

    try:
        # # Open left valve (Channel 1, register 0x0000) – Write Single Coil (Function 05), 0xFF00 = ON
        # instrument.write_bit(0x0000, 1)
        # logger.info("Left valve opened")
        # time.sleep(2)

        # # Close left valve (Channel 1) – 0x0000 = OFF
        # instrument.write_bit(0x0000, 0)
        # logger.info("Left valve closed")
        # time.sleep(2)

        # # Open right valve (Channel 2, register 0x0001) – 0xFF00 = ON
        # instrument.write_bit(1, 1)
        # logger.info("Right valve opened")
        # time.sleep(2)

        # # Close right valve (Channel 2) – 0x0000 = OFF
        # instrument.write_bit(1, 0)
        # logger.info("Right valve closed")
        # time.sleep(1)
        
        # Cycle through 8 valves 10 times.
        for cycle in range(10):
            for coil in range(8):
                # Open valve (Function 05, 0xFF00)
                instrument.write_bit(coil, 1)
                logger.info(f"Valve {coil+1} opened")
                time.sleep(0.1)
                # Close valve (0x0000)
                instrument.write_bit(coil, 0)
                logger.info(f"Valve {coil+1} closed")
                time.sleep(0.1)

    except Exception as e:
        logger.error("Modbus error during valve cycle", exc_info=e)
    finally:
        logger.info("Valve cycle complete")
        # Close serial port on exit
        try:
            if instrument.serial.is_open:
                instrument.serial.close()
                logger.info("Serial port closed")
        except Exception as e:
            logger.warning("Failed to close serial port", exc_info=e)

if __name__ == "__main__":
    main()