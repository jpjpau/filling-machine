#!/usr/bin/env python3
import minimalmodbus
import serial
import time
import logging

# Optional: enable debug logging from minimalmodbus
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    # Configure the valve controller instrument
    instrument = minimalmodbus.Instrument("/dev/ttyCH9344USB8", 1)  # port, slave address
    instrument.mode = minimalmodbus.MODE_RTU
    instrument.serial.baudrate = 9600
    instrument.serial.timeout = 0.5
    instrument.serial.parity = serial.PARITY_NONE
    instrument.serial.bytesize = 8
    instrument.serial.stopbits = 1
    instrument.clear_buffers_before_each_transaction = True
    instrument.close_port_after_each_call = False

    try:
        # Open left valve (coil 1)
        #instrument.write_register(0x0000, 0xFF00)
        instrument.write_bit(0, 1)
        logger.info("Left valve opened")
        time.sleep(1)

        # Close left valve
        #instrument.write_register(0x0000, 0x0000)
        instrument.write_bit(0, 0)
        instrument.write_bit(1, 1)
        logger.info("Left valve closed")
        time.sleep(1)

        # Open right valve (coil 2)
        #instrument.write_register(0x0001, 0xFF00)
        #instrument.write_bit(2, 1)
        logger.info("Right valve opened")
        time.sleep(1)

        # Close right valve
        #instrument.write_register(0x0001, 0x0000)
        logger.info("Right valve closed")
        
        if instrument.serial.is_open:
            instrument.serial.close()

    except Exception as e:
        logger.error("Modbus error during valve cycle", exc_info=e)
    finally:
        logger.info("Valve cycle complete")

if __name__ == "__main__":
    main()