# preview_ui.py
from config import Config
from ui.ui_manager import UIManager
from machine.controller import MachineController

# A minimal stub controller with just the attributes/UI hooks your UI needs
class DummyController:
    def __init__(self):
        # load the real flavour list so your dropdown is populated
        self.config = Config()
        from machine.controller import MachineController
        self._state = MachineController.STATE_WAITING_FOR_MOULD
        self.speed_fast = self.config.get("fast_speed")
        self.speed_slow = self.config.get("slow_speed")
        # starting values for the labels and slider
        self.vfd_speed      = 0
        self.actual_weight  = 0.0
        # stub out modbus calls for the prime buttons
        class DummyModbus:
            def set_valve(self, valve, action): pass
        self.modbus = DummyModbus()

# Instantiate & show the UI
if __name__ == "__main__":
    ctrl = DummyController()
    ui   = UIManager(ctrl)
    ui.run()