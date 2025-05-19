#!/usr/bin/env python3
import minimalmodbus
import serial
import time
import statistics
import sys

# --- Load‐cell Modbus settings (match your ModbusInterface) ---
PORT       = '/dev/ttyCH9344USB1'
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

    # Frequency sweep test variables
    start_interval = 0.25
    min_interval = 0.001
    step = 0.01
    reads_per_test = 50

    interval = start_interval
    print("Starting frequency sweep...")
    while interval >= min_interval:
        successes = []
        errors = 0
        print(f"\nTesting interval = {interval:.3f}s ...", end="", flush=True)
        for i in range(reads_per_test):
            t0 = time.time()
            try:
                raw = read_raw(inst)
                w = raw_to_kg(raw) - tare
                successes.append(time.time() - t0)
            except Exception as e:
                errors += 1
            time.sleep(interval)
        if successes:
            avg = statistics.mean(successes)
            stddev = statistics.stdev(successes) if len(successes) > 1 else 0.0
            print(f" Successes={len(successes)}/{reads_per_test}, errors={errors}, avg_read={avg*1000:.1f}ms ±{stddev*1000:.1f}ms")
        else:
            print(f" All {reads_per_test} reads failed.")
        interval -= step
    print("\nFrequency sweep complete.")
    sys.exit(0)

if __name__ == '__main__':
    main()