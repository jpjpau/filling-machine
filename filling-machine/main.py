from config import Config
from machine.modbus_interface import ModbusInterface
from machine.mqtt_client      import MqttClient
from machine.controller       import MachineController
from ui.ui_manager            import UIManager
import time
import logging
import logging.handlers
import os
from datetime import datetime
import socket
import subprocess

# Create a logs directory if it doesn't exist
os.makedirs("logs", exist_ok=True)
log_filename = datetime.now().strftime("logs/filling_machine_%Y%m%d_%H%M%S.log")

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# File handler with date/time-based log filename
file_handler = logging.FileHandler(log_filename)
file_handler.setLevel(logging.INFO)
file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Syslog handler (UDP to remote syslog server)
syslog_handler = logging.handlers.SysLogHandler(address=('192.168.15.6', 514), socktype=socket.SOCK_DGRAM)
syslog_formatter = logging.Formatter('%(name)s: %(levelname)s %(message)s')
syslog_handler.setFormatter(syslog_formatter)
logger.addHandler(syslog_handler)

def main():
    # Kill any process holding the serial ports ttyCH9344USB0 through ttyCH9344USB7
    for i in range(8):
        dev = f"/dev/ttyCH9344USB{i}"
        try:
            subprocess.run(["fuser", "-k", dev], check=True)
            logger.info(f"Killed processes using {dev}")
        except Exception as e:
            logger.warning(f"Failed to kill processes using {dev}: {e}")
    # 1. Load configuration
    cfg = Config()

    # 2. Initialize hardware interfaces
    modbus = ModbusInterface(cfg)
    time.sleep(1)
    mqtt   = MqttClient(cfg.get("mqttBroker"))

    # 3. Create controller and UI
    controller = MachineController(cfg, modbus, mqtt)
    ui = UIManager(controller)

    # 4. Start the machine threads and UI loop
    try:
        controller.start()
        ui.run()
    finally:
        # Ensure we always cleanly shut down the hardware threads
        controller.stop()
        logger.info("Application exited cleanly")

if __name__ == "__main__":
    main()