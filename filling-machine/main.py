from config import Config
from machine.modbus_interface import ModbusInterface
from machine.mqtt_client      import MqttClient
from machine.controller       import MachineController
from ui.ui_manager            import UIManager

def main():
    # 1. Load configuration
    cfg = Config()

    # 2. Initialize hardware interfaces
    modbus = ModbusInterface()
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