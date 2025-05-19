from config import Config
from machine.modbus_interface import ModbusInterface
from machine.mqtt_client      import MqttClient
from machine.controller       import MachineController
from ui.ui_manager            import UIManager
import time

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

if __name__ == "__main__":
    main()