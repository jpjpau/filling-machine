import tkinter as tk
from tkinter import ttk
import tkinter.font as tkFont

class UIManager:
    """
    Manages the Tkinter UI with Clean and Fill tabs, interacting with MachineController.
    """
    def __init__(self, controller):
        self.controller = controller
        self.cleaning = False

        # Increase button/tab font and padding for touchscreen
        style = ttk.Style()
        default_font = tkFont.Font(size=20)
        style.configure('TNotebook.Tab', font=default_font, padding=[10, 10])

        # Main window
        self.root = tk.Tk()
        self.root.title("Filling Machine Control")
        self.root.attributes('-fullscreen', True)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True)

        # --- Clean Tab ---
        clean_tab = ttk.Frame(self.notebook)
        self.notebook.add(clean_tab, text="Clean")

        clean_frame = ttk.Frame(clean_tab)
        clean_frame.pack(pady=20)
        self.clean_button = ttk.Button(clean_frame, text="Clean", command=self.toggle_clean,
                                       font=default_font, width=12, height=2)
        self.clean_button.grid(row=0, column=0, padx=10)
        exit_button = ttk.Button(clean_frame, text="Exit", command=self.on_close,
                                 font=default_font, width=12, height=2)
        exit_button.grid(row=0, column=1, padx=10)

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

        # Weight display
        weight_frame = ttk.LabelFrame(fill_tab, text="Weight (kg)")
        weight_frame.pack(fill="x", padx=10, pady=5)
        self.weight_label = ttk.Label(
            weight_frame,
            text=f"{self.controller.actual_weight:.2f}",
            font=(None, 16)
        )
        self.weight_label.pack(padx=5, pady=5)

        # Speed settings
        speed_frame = ttk.LabelFrame(fill_tab, text="VFD Speed Settings")
        speed_frame.pack(fill="x", padx=10, pady=5)

        # Fast speed slider
        ttk.Label(speed_frame, text="Fast Speed (Hz):").pack(anchor="w", padx=5)
        self.fast_speed_var = tk.DoubleVar(value=self.controller.speed_fast)
        ttk.Scale(
            speed_frame,
            from_=50,
            to=150,
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
            from_=5,
            to=50,
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
                                      font=default_font, width=16, height=2)
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
        for flavour in self.controller.config.volumes.keys():
            f_frame = ttk.Frame(adjust_frame)
            f_frame.pack(fill="x", pady=2)
            ttk.Label(f_frame, text=flavour).pack(side="left", padx=5)
            var = tk.DoubleVar(value=self.controller.config.get(flavour))
            self.flavour_vars[flavour] = var
            ttk.Label(f_frame, textvariable=var, width=6).pack(side="right", padx=5)
            ttk.Button(f_frame, text="+", command=lambda f=flavour: self.adjust_flavour(f, 0.1),
                       font=default_font, width=4, height=2).pack(side="right")
            ttk.Button(f_frame, text="−", command=lambda f=flavour: self.adjust_flavour(f, -0.1),
                       font=default_font, width=4, height=2).pack(side="right", padx=2)
        save_btn = ttk.Button(adjust_frame, text="Save Flavours", command=self.save_flavours,
                              font=default_font, width=16, height=2)
        save_btn.pack(pady=5)

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
        self.controller.stop()
        self.root.destroy()

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
        self.weight_label.config(text=f"{self.controller.actual_weight:.2f}")
        self.status_label.config(text=self.controller._state)
        self.fast_speed_label.config(text=f"{self.controller.speed_fast:.2f} Hz")
        self.slow_speed_label.config(text=f"{self.controller.speed_slow:.2f} Hz")
        # Schedule next update
        self.root.after(100, self.update_ui)
