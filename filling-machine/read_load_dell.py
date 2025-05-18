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

def read_raw(inst):
    return inst.read_long(LOADCELL_REG, functioncode=FUNCTION_CODE)

def raw_to_kg(raw):
    # Convert two’s‐complement 32‐bit signed to Python int then grams→kg
    if raw > 0x7FFFFFFF:
        raw -= 0x100000000
    return raw / 1000.0

def main():
    print(f"Connecting to load cell on {PORT} @ addr {SLAVE_ADDR}…")
    inst = setup_instrument()

    # Tare: take a quick average of a few readings at startup
    print("Taring...", end="", flush=True)
    samples = []
    for _ in range(5):
        try:
            samples.append(raw_to_kg(read_raw(inst)))
        except Exception as e:
            print(f"\n  Error during tare read: {e}")
        time.sleep(0.1)
    tare = sum(samples) / len(samples) if samples else 0.0
    print(f" done. Tare offset = {tare:.3f} kg\n")

    try:
        while True:
            try:
                w = raw_to_kg(read_raw(inst)) - tare
                print(f"Weight: {w:+.3f} kg")
            except Exception as e:
                print(f"Error reading load cell: {e}")
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nExiting.")

if __name__ == '__main__':
    main()