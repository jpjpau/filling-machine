import tkinter as tk
from tkinter import ttk

class UIManager:
    """
    Manages the Tkinter UI and binds user actions to the MachineController.
    """
    def __init__(self, controller):
        self.controller = controller
        self.root = tk.Tk()
        self.root.title("Filling Machine Control")

        # ----- Flavour Selection -----
        flavour_frame = ttk.LabelFrame(self.root, text="Select Flavour")
        flavour_frame.pack(fill="x", padx=10, pady=5)

        # Use the config.volumes keys for options
        options = list(self.controller.config.volumes.keys())
        self.flavour_var = tk.StringVar(value=options[0])
        self.flavour_menu = ttk.OptionMenu(
            flavour_frame,
            self.flavour_var,
            options[0],
            *options,
            command=self.on_flavour_change
        )
        self.flavour_menu.pack(anchor="w", padx=5, pady=5)

        # ----- Weight Display -----
        weight_frame = ttk.Frame(self.root)
        weight_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(weight_frame, text="Actual Weight:").pack(side="left")
        self.weight_label = ttk.Label(weight_frame, text="0.000 kg", font=(None, 12, 'bold'))
        self.weight_label.pack(side="left", padx=5)

        # ----- Speed Settings -----
        speed_settings = ttk.LabelFrame(self.root, text="VFD Speed Settings")
        speed_settings.pack(fill="x", padx=10, pady=5)

        # Fast speed (Hz)
        ttk.Label(speed_settings, text="Fast Speed (Hz):").pack(anchor="w", padx=5)
        self.fast_speed_var = tk.DoubleVar(value=self.controller.speed_fast)
        fast_scale = ttk.Scale(
            speed_settings,
            from_=0,
            to=200,
            variable=self.fast_speed_var,
            command=self.on_fast_speed_change
        )
        fast_scale.pack(fill="x", padx=5)
        self.fast_speed_label = ttk.Label(speed_settings, text=f"{self.controller.speed_fast:.2f} Hz")
        self.fast_speed_label.pack(padx=5, pady=(0,5))

        # Slow speed (Hz)
        ttk.Label(speed_settings, text="Slow Speed (Hz):").pack(anchor="w", padx=5)
        self.slow_speed_var = tk.DoubleVar(value=self.controller.speed_slow)
        slow_scale = ttk.Scale(
            speed_settings,
            from_=0,
            to=200,
            variable=self.slow_speed_var,
            command=self.on_slow_speed_change
        )
        slow_scale.pack(fill="x", padx=5)
        self.slow_speed_label = ttk.Label(speed_settings, text=f"{self.controller.speed_slow:.2f} Hz")
        self.slow_speed_label.pack(padx=5, pady=(0,5))

        # ----- Prime Controls -----
        prime_frame = ttk.LabelFrame(self.root, text="Prime Valves")
        prime_frame.pack(fill="x", padx=10, pady=5)

        btn1 = ttk.Button(
            prime_frame,
            text="Prime Valve 1",
            command=lambda: self.controller.modbus.set_valve("left", "open")
        )
        btn1.pack(side="left", padx=5, pady=5)

        btn2 = ttk.Button(
            prime_frame,
            text="Prime Valve 2",
            command=lambda: self.controller.modbus.set_valve("right", "open")
        )
        btn2.pack(side="left", padx=5, pady=5)

        btn_stop = ttk.Button(
            prime_frame,
            text="Stop Prime",
            command=lambda: self.controller.modbus.set_valve("both", "close")
        )
        btn_stop.pack(side="left", padx=5, pady=5)

        # ----- Status Display -----
        status_frame = ttk.Frame(self.root)
        status_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(status_frame, text="Machine State:").pack(side="left")
        self.status_label = ttk.Label(status_frame, text=self.controller._state, font=(None, 12, 'bold'))
        self.status_label.pack(side="left", padx=5)

        # ----- Window Closing -----
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def on_flavour_change(self, value):
        """
        Called when the flavour dropdown changes.
        """
        self.controller.select_flavour(value)


    def on_fast_speed_change(self, val):
        speed = float(val)
        # Update controller setting (in Hz)
        self.controller.speed_fast = speed
        self.fast_speed_label.config(text=f"{speed:.2f} Hz")

    def on_slow_speed_change(self, val):
        speed = float(val)
        self.controller.speed_slow = speed
        self.slow_speed_label.config(text=f"{speed:.2f} Hz")

    def update_ui(self):
        """
        Periodically update dynamic labels from controller state.
        """
        # Update weight display
        wt = self.controller.actual_weight
        self.weight_label.config(text=f"{wt:.3f} kg")

        # Update machine state
        self.status_label.config(text=self.controller._state)
        # Update speed labels
        self.fast_speed_label.config(text=f"{self.controller.speed_fast:.2f} Hz")
        self.slow_speed_label.config(text=f"{self.controller.speed_slow:.2f} Hz")

        # Schedule next update
        self.root.after(100, self.update_ui)

    def run(self):
        """
        Start the UI loop. Should be called after controller.start().
        """
        self.update_ui()
        self.root.mainloop()

    def on_close(self):
        """
        Clean shutdown on window close.
        """
        self.root.quit()