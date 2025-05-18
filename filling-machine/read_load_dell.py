#!/usr/bin/env python3
import minimalmodbus
import serial
import time

# --- Load‐cell Modbus settings (match your ModbusInterface) ---
PORT       = '/dev/ttySC0'
SLAVE_ADDR = 1
BAUDRATE   = 9600
TIMEOUT    = 0.2

# Register address and function code
LOADCELL_REG    = 0x0000
FUNCTION_CODE   = 3

def setup_instrument():
    inst = minimalmodbus.Instrument(PORT, SLAVE_ADDR, mode=minimalmodbus.MODE_RTU)
    inst.serial.baudrate = BAUDRATE
    inst.serial.timeout  = TIMEOUT
    inst.serial.parity   = serial.PARITY_NONE
    inst.serial.bytesize = 8
    inst.serial.stopbits = 1
    inst.clear_buffers_before_each_transaction = True
    inst.close_port_after_each_call = True
    return inst

def read_weight(inst):
    raw = inst.read_long(LOADCELL_REG, functioncode=FUNCTION_CODE)
    # Convert two’s‐complement 32‐bit signed to Python int
    if raw > 0x7FFFFFFF:
        raw -= 0x100000000
    return raw / 1000.0  # grams → kg

def main():
    print(f"Connecting to load cell on {PORT} @ addr {SLAVE_ADDR}…")
    inst = setup_instrument()
    try:
        while True:
            try:
                w = read_weight(inst)
                print(f"Weight: {w:.3f} kg")
            except Exception as e:
                print(f"Error reading load cell: {e}")
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nExiting.")
        # nothing special to close since we close port after each call

if __name__ == '__main__':
    main()