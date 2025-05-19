import minimalmodbus
import serial

# Configure the serial port and slave ID
instrument = minimalmodbus.Instrument("/dev/ttyCH9344USB2", 2, minimalmodbus.MODE_ASCII)  # (port, slave address)
instrument.serial.baudrate = 19200                         # Set to match your VFD settings
instrument.serial.bytesize = 8
instrument.serial.parity   = serial.PARITY_NONE
instrument.serial.stopbits = 1
instrument.serial.timeout  = 1                            # seconds

# Register settings
register_address = 0x0112  # 274 in decimal
value_to_write = 5
function_code = 6          # Write single holding register

try:
    instrument.write_register(register_address, value_to_write, 0, functioncode=function_code)
    print(f"Successfully wrote {value_to_write} to register 0x{register_address:04X}")
except Exception as e:
    print(f"Failed to write to register: {e}")