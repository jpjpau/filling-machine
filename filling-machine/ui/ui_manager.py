import tkinter as tk
from tkinter import ttk
import tkinter.font as tkFont
import logging

class UIManager:
    """
    Manages the Tkinter UI with Clean and Fill tabs, interacting with MachineController.
    """
    def __init__(self, controller):
        self.controller = controller
        self.cleaning = False

        # Main window
        self.root = tk.Tk()
        # Style configuration (after root exists to avoid stray windows)
        style = ttk.Style(self.root)
        style.theme_use('clam')
        default_font = tkFont.Font(size=20)
        style.configure('TNotebook.Tab', font=default_font, padding=[24, 16])
        style.configure('Large.TButton', font=default_font, padding=[20, 20])
        # Define a smaller button style for settings controls
        small_font = tkFont.Font(size=14)
        style.configure('Small.TButton', font=small_font, padding=[5,5])
        self.root.title("Filling Machine Control")
        self.root.attributes('-fullscreen', True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True)
        # Enable filling only when Fill tab is selected
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)

        # --- Clean Tab ---
        clean_tab = ttk.Frame(self.notebook)
        self.notebook.add(clean_tab, text="Clean")

        clean_frame = ttk.Frame(clean_tab)
        clean_frame.pack(pady=20)
        self.clean_button = ttk.Button(clean_frame, text="Clean", command=self.toggle_clean,
                                       style='Large.TButton', width=16)
        self.clean_button.grid(row=0, column=0, padx=10)
        exit_button = ttk.Button(clean_frame, text="Exit", command=self.on_close,
                                 style='Large.TButton', width=16)
        exit_button.grid(row=0, column=1, padx=10)

        # Cleaning speed slider
        speed_clean_frame = ttk.LabelFrame(clean_tab, text="Cleaning Speed (Hz)")
        speed_clean_frame.pack(fill="x", padx=10, pady=5)
        self.clean_speed_var = tk.DoubleVar(value=self.controller.clean_speed)
        ttk.Scale(
            speed_clean_frame,
            from_=5,
            to=150,
            variable=self.clean_speed_var,
            command=self.on_clean_speed_change
        ).pack(fill="x", padx=5)
        self.clean_speed_label = ttk.Label(
            speed_clean_frame,
            text=f"{self.controller.clean_speed:.2f} Hz"
        )
        self.clean_speed_label.pack(padx=5, pady=(0,5))

        # --- Fill Tab ---
        fill_tab = ttk.Frame(self.notebook)
        self.notebook.add(fill_tab, text="Fill")

        # Flavour selection
        flavour_frame = ttk.LabelFrame(fill_tab, text="Select Flavour")
        flavour_frame.pack(fill="x", padx=10, pady=5)
        self.flavour_var = tk.StringVar(value=list(self.controller.config.volumes.keys())[0])
        self.flavour_menu = ttk.OptionMenu(
            flavour_frame,
            self.flavour_var,
            self.flavour_var.get(),
            *self.controller.config.volumes.keys(),
            command=self.on_flavour_change
        )
        self.flavour_menu.pack(fill="x", padx=5)

        # --- Measurements ---
        meas_frame = ttk.LabelFrame(fill_tab, text="Measurements")
        meas_frame.pack(fill="x", padx=10, pady=5)
        # Layout measurement labels in a row
        font_size = 14
        self.total_weight_label = ttk.Label(
            meas_frame,
            text=f"Total: {self.controller.actual_weight:.2f} kg",
            font=(None, font_size)
        )
        self.total_weight_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.tare_weight_label = ttk.Label(
            meas_frame,
            text=f"Tare: {self.controller._tare_weight:.2f} kg",
            font=(None, font_size)
        )
        self.tare_weight_label.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        self.left_pour_label = ttk.Label(
            meas_frame,
            text="Left Pour: 0.00 kg",
            font=(None, font_size)
        )
        self.left_pour_label.grid(row=0, column=2, padx=10, pady=5, sticky="w")
        self.right_pour_label = ttk.Label(
            meas_frame,
            text="Right Pour: 0.00 kg",
            font=(None, font_size)
        )
        self.right_pour_label.grid(row=0, column=3, padx=10, pady=5, sticky="w")

        # Speed settings
        speed_frame = ttk.LabelFrame(fill_tab, text="VFD Speed Settings")
        speed_frame.pack(fill="x", padx=10, pady=5)

        # Fast speed slider
        ttk.Label(speed_frame, text="Fast Speed (Hz):").pack(anchor="w", padx=5)
        self.fast_speed_var = tk.DoubleVar(value=self.controller.speed_fast)
        ttk.Scale(
            speed_frame,
            from_=5,
            to=50,
            variable=self.fast_speed_var,
            command=self.on_fast_speed_change
        ).pack(fill="x", padx=5)
        self.fast_speed_label = ttk.Label(
            speed_frame,
            text=f"{self.controller.speed_fast:.2f} Hz"
        )
        self.fast_speed_label.pack(padx=5, pady=(0,5))

        # Slow speed slider
        ttk.Label(speed_frame, text="Slow Speed (Hz):").pack(anchor="w", padx=5)
        self.slow_speed_var = tk.DoubleVar(value=self.controller.speed_slow)
        ttk.Scale(
            speed_frame,
            from_=0.5,
            to=30,
            variable=self.slow_speed_var,
            command=self.on_slow_speed_change
        ).pack(fill="x", padx=5)
        self.slow_speed_label = ttk.Label(
            speed_frame,
            text=f"{self.controller.speed_slow:.2f} Hz"
        )
        self.slow_speed_label.pack(padx=5, pady=(0,5))

        # Prime button (press-and-hold)
        prime_frame = ttk.Frame(fill_tab)
        prime_frame.pack(pady=10)
        self.prime_button = ttk.Button(prime_frame, text="Prime",
                                       style='Large.TButton', width=20)
        self.prime_button.pack()
        self.prime_button.bind("<ButtonPress>", self.on_prime_press)
        self.prime_button.bind("<ButtonRelease>", self.on_prime_release)

        # Status display
        status_frame = ttk.Frame(fill_tab)
        status_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(status_frame, text="Machine State:").pack(side="left")
        self.status_label = ttk.Label(
            status_frame,
            text=self.controller._state,
            font=(None, 12, 'bold')
        )
        self.status_label.pack(side="left", padx=5)

        # --- Settings Tab ---
        settings_tab = ttk.Frame(self.notebook)
        self.notebook.add(settings_tab, text="Settings")

        # Flavour adjustment controls moved to Settings tab
        adjust_frame = ttk.LabelFrame(settings_tab, text="Flavour Settings")
        adjust_frame.pack(fill="x", padx=10, pady=5)
        self.flavour_vars = {}
        # Create two columns for flavour settings
        left_adjust_frame = ttk.Frame(adjust_frame)
        left_adjust_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        right_adjust_frame = ttk.Frame(adjust_frame)
        right_adjust_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        adjust_frame.columnconfigure(0, weight=1)
        adjust_frame.columnconfigure(1, weight=1)
        flavours = list(self.controller.config.volumes.keys())
        half = (len(flavours) + 1) // 2
        for idx, flavour in enumerate(flavours):
            parent = left_adjust_frame if idx < half else right_adjust_frame
            row = idx if idx < half else idx - half
            ttk.Label(parent, text=flavour).grid(row=row, column=0, sticky="w", padx=5)
            var = tk.DoubleVar(value=self.controller.config.get(flavour))
            self.flavour_vars[flavour] = var
            ttk.Label(parent, textvariable=var, width=6).grid(row=row, column=1, padx=5)
            ttk.Button(parent, text="−", command=lambda f=flavour: self.adjust_flavour(f, -0.01),
                       style='Small.TButton', width=2).grid(row=row, column=2, padx=2)
            ttk.Button(parent, text="+", command=lambda f=flavour: self.adjust_flavour(f, 0.01),
                       style='Small.TButton', width=2).grid(row=row, column=3)
        save_btn = ttk.Button(adjust_frame, text="Save Settings", command=self.save_flavours,
                              style='Small.TButton', width=11)
        save_btn.grid(row=1, column=0, columnspan=2, pady=5)

        # Kick off update loop
        self.root.after(100, self.update_ui)

    def save_flavours(self):
        """Persist flavour changes to config.json."""
        self.controller.config.save()

    def adjust_flavour(self, flavour, delta):
        """Adjust a flavour volume by delta and update config."""
        current = self.controller.config.get(flavour)
        new_val = round(current + delta, 2)
        self.controller.config.set(flavour, new_val)
        self.flavour_vars[flavour].set(new_val)

    def run(self):
        self.root.mainloop()

    def on_close(self):
        """Handle exit: stop controller and exit UI."""
        logging.info("UIManager: exit requested")
        try:
            self.controller.stop()
        except Exception:
            logging.exception("Error while stopping controller")
        # Quit the Tkinter mainloop to allow the script to continue and exit
        self.root.quit()

    def on_flavour_change(self, name):
        self.controller.select_flavour(name)

    def on_fast_speed_change(self, val):
        speed = float(val)
        self.controller.speed_fast = speed
        self.fast_speed_label.config(text=f"{speed:.2f} Hz")

    def on_slow_speed_change(self, val):
        speed = float(val)
        self.controller.speed_slow = speed
        self.slow_speed_label.config(text=f"{speed:.2f} Hz")

    def on_prime_press(self, event):
        # Open both valves and start VFD at fast speed
        self.controller.modbus.set_valve("both", "open")
        self.controller.vfd_state = 6
        self.controller.vfd_speed = int(self.controller.speed_fast * 100)

    def on_prime_release(self, event):
        # Stop VFD and close valves
        self.controller.vfd_state = 0
        self.controller.vfd_speed = 0
        self.controller.modbus.set_valve("both", "close")

    def on_tab_changed(self, event):
        """Enable filling in controller when Fill tab is selected."""
        selected = self.notebook.tab(self.notebook.select(), "text")
        if selected == "Fill":
            self.controller.enable_filling()

    def toggle_clean(self):
        if not self.cleaning:
            self.clean_button.config(text="Stop")
            self.controller.start_clean_cycle()
            self.cleaning = True
        else:
            self.controller.stop_clean_cycle()
            self.clean_button.config(text="Clean")
            self.cleaning = False

    def update_ui(self):
        # Refresh dynamic labels
        self.status_label.config(text=self.controller._state)
        self.fast_speed_label.config(text=f"{self.controller.speed_fast:.2f} Hz")
        self.slow_speed_label.config(text=f"{self.controller.speed_slow:.2f} Hz")
        # Update measurements
        self.total_weight_label.config(text=f"Total: {self.controller.actual_weight:.2f} kg")
        self.tare_weight_label.config(text=f"Tare: {self.controller._tare_weight:.2f} kg")

        # Determine left pour: dynamic during left fill then persist
        if self.controller._state in (self.controller.STATE_FILL_LEFT_FAST, self.controller.STATE_FILL_LEFT_SLOW):
            left_pour = self.controller.actual_weight - self.controller._tare_weight
            self.controller.last_left_pour = left_pour
        else:
            left_pour = getattr(self.controller, 'last_left_pour', 0.0)

        # Determine right pour: dynamic during right fill then persist
        if self.controller._state in (self.controller.STATE_FILL_RIGHT_FAST, self.controller.STATE_FILL_RIGHT_SLOW):
            right_pour = self.controller.actual_weight - self.controller._tare_weight
            self.controller.last_right_pour = right_pour
        else:
            right_pour = getattr(self.controller, 'last_right_pour', 0.0)

        self.left_pour_label.config(text=f"Left Pour: {left_pour:.2f} kg")
        self.right_pour_label.config(text=f"Right Pour: {right_pour:.2f} kg")
        # Schedule next update
        self.root.after(30, self.update_ui)

    def on_clean_speed_change(self, val):
        speed = float(val)
        self.controller.clean_speed = speed
        self.clean_speed_label.config(text=f"{speed:.2f} Hz")