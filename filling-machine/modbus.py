import minimalmodbus

def setup_modbus(mb_address, port, timeout, baudrate, parity):
    ##### MODBUS SETUP #####
    USB_port = "/dev/ttySC" + str(port)
    # baudrate = 9600							# BaudRate
    bytesize = 8							# Number of data bits to be requested
    stopbits = 1							# Number of stop bits
    # timeout = 0.4							# Timeout time in seconds
    clear_buffers_before_call = True		# Good practice clean up
    clear_buffers_after_call  = True	
    modbus = minimalmodbus.Instrument(USB_port,mb_address)
    modbus.mode = minimalmodbus.MODE_RTU
    if parity == "even":
        modbus.serial.parity = minimalmodbus.serial.PARITY_EVEN
    elif parity == "odd":
        modbus.serial.parity = minimalmodbus.serial.PARITY_ODD
    elif parity == "none":
        modbus.serial.parity = minimalmodbus.serial.PARITY_NONE

    # modbus.serial.parity = minimalmodbus.serial.PARITY_NONE
    modbus.serial.baudrate = baudrate
    modbus.serial.bytesize = bytesize
    modbus.serial.stopbits = stopbits		
    modbus.serial.timeout  = timeout
    modbus.clear_buffers_before_each_transaction = clear_buffers_before_call
    modbus.close_port_after_each_call = clear_buffers_after_call 
    return (modbus)

##### MODBUS SETUP #####
turny_boi = setup_modbus(2, 1, 0.2, 19200, "even")
load_cell = setup_modbus(1, 0, 0.2, 9600, "none")
valves = setup_modbus(3, 0, 0.4, 9600, "none")

# adding some comments
