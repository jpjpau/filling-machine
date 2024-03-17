#Git Test 1
# This script has been split into multiple files
# Filling-MODBUS.py handles all the MODBUS creation tasks as well as MODBUS messaging

# influxdb api nQ7wJ20hv3kWwLVPeV6RDstRgRPnx4wMsG58ILw75Ak30qXwoCOwSwRtERfKhCW8KHIsMEEyae-ZbjqujQQnAw==
# sA91iKW50uVu7zJ4VCShP39qJDrHQh9vmhJzqE68D5CkKta31RMSaOIXd_ayuKdNjrb9bSq9CrV9oYLN_RyI6A==

import modbus
import tkinter as tk
from tkinter import ttk
import serial
import time
import threading
import RPi.GPIO as GPIO
import time
from random import randrange, uniform
import paho.mqtt.client as mqtt 
import csv
from datetime import datetime
from gpiozero import CPUTemperature
cpu = CPUTemperature()
import logging
import logging.handlers
import os
import cv2
from os.path import exists
from collections import deque 
que_length = 5
lc_que = deque([0]*que_length,que_length) 

try:
    mqttBroker ="192.168.15.70" 
    mqtt_client = mqtt.Client("Filling_Machine")
    mqtt_client.connect(mqttBroker) 
except Exception as e:
    logging.exception("MQTT Cannot contact MQTT server - " + str(e))

cam = cv2.VideoCapture(0)

now = datetime.now()
dt_string = now.strftime("%Y-%m-%d %H-%M-%S")
csv_f = open('/home/pi/filling_records/' + dt_string + '.csv', 'x')
csv_file = csv.writer(csv_f)
header = ['time', 'batch', 'mould weight', 'flavour', 'set weight', 'set high speed', 'set low speed', 'mould 1 weight', 'mould 1 fill time', 'mould 2 weight', 'mould 2 fill time','cpu temp']
csv_file.writerow(header)

kill_all = False

syslogging = logging.handlers.SysLogHandler(address=("192.168.15.70", 1514))
root = logging.getLogger()
root.setLevel(logging.INFO)
root.setLevel(os.environ.get("LOGLEVEL", "INFO"))
root.addHandler(syslogging)

vfd_state = 6
vfd_speed = 0
tare = 0
valve1, valve2 = 0, 0

publish_weight_timer = 0

Food_Service = 1.5
Brie = 2.11
SM_CO_GCO = 1.35 # added 50g 24th Feb
H_GPH = 1.3 # added 50g 24th Feb
Essent_Mozz = 0.66
Essent_Ched = 0.8
focus = "Clean"
actual_weight = 0
start_time = time.time()
mould_weight = 1.2

Food_Service_mould = 1.2
Brie_mould = 1.3
SM_CO_GCO_mould = 1.2
H_GPH_mould = 1.02
Essent_Mozz_Mould = 1.2
Essent_Ched_Mould = 1.2

motor_start_time = 0

filling_status = 0
#0 = stopped, waiting for mould.
# 1 = mould detected, waiting to confirm.
# 2 = filling started.
# 3 = filling slowing.
# 4 = filling stopped.
# 5 = filling finished, waiting to remove mould
# 6 = getting ready to fill mould 2
# 7 = start filling mould 2
# 8 = slow down filling mould 2
# 9 = stop filling mould 2

current_weight = 0

mould_detected_count = 0

root = tk.Tk()
root.title("Counter") 
root.attributes("-fullscreen", True)

tabControl = ttk.Notebook(root)
fillingtab = ttk.Frame(tabControl)
cleaningtab = ttk.Frame(tabControl)
tabControl.add(cleaningtab, text ='Cleaning & Close')
tabControl.add(fillingtab, text ='Filling')
tabControl.pack(expand = 1, fill ="both")

display_weight = tk.StringVar()
display_weight.set(0)
high_speed = tk.StringVar()
high_speed.set(3500)
low_speed = tk.StringVar()
low_speed.set(800)
previous_label = tk.StringVar()
previous_label.set("Ready")
mould_count = tk.IntVar()
mould_count.set(0)
selected = tk.StringVar()
selected.set("SM / CO / GCO")
desired_volume = tk.StringVar()
style = ttk.Style(root)
style.configure('TRadiobutton', font=('Helvetica', 21))
style.configure('TNotebook', tabmargins=(2, 5, 2, 0))
style.configure('TNotebook.Tab', padding=(100, 15), font=('Helvetica', 21))

batch_number = tk.StringVar()

current_weight_frame = tk.LabelFrame(fillingtab, text="Current Weight", relief='raised', borderwidth='1', padx=1, pady=1, font=("Arial", 12))
previous_weight_frame = tk.LabelFrame(fillingtab, text="Previous Weight", relief='raised', borderwidth='1', padx=1, pady=1, font=("Arial", 12))
current_batch_frame = tk.LabelFrame(fillingtab, text="Batch", relief='raised', borderwidth='1', padx=1, pady=1, font=("Arial", 12))

desired_volume_frame = tk.LabelFrame(fillingtab, text="Target Volume", relief='raised', borderwidth='1', padx=1, pady=1, font=("Arial", 12))
filling_options_frame = tk.LabelFrame(fillingtab, text="Filling Options", relief='raised', borderwidth='1', padx=1, pady=1, font=("Arial", 12))
high_speed_frame = tk.LabelFrame(fillingtab, text="Pump - High Speed", relief='raised', borderwidth='1', padx=1, pady=1, font=("Arial", 12))
low_speed_frame = tk.LabelFrame(fillingtab, text="Pump - Low Speed", relief='raised', borderwidth='1', padx=1, pady=1, font=("Arial", 12))

label_current_weight = tk.Label(current_weight_frame, width=10, font=("Arial", 20), textvariable=display_weight)
label_previous_weight = tk.Label(previous_weight_frame, width=10, font=("Arial", 20), textvariable=previous_label)
label_current_batch = tk.Label(current_batch_frame, width=10, font=("Arial", 20), textvariable=batch_number)

actual_mould_weight = 0

def Close():
    global vfd_speed, vfd_state, kill_all, valve2, valve1
    #modbus.load_cell.write_long(0x0000, 0, False, 0)
    stop=6
    vfd_state = stop
    vfd_speed = 0
    time.sleep(0.2)
    kill_all = True
    valve1, valve2 = 0, 0
    time.sleep(0.2)
    GPIO.cleanup()
    csv_f.close()
    cam.release()
    root.destroy()

button_close = tk.Button(cleaningtab, text="Exit", font=("Arial", 40), command=Close, width=10, height=2, padx=10, pady=10)

priming = 0
cleaning = 0

def get_batch(var1):
    global batch_number, tabControl, display_batch
    selectedTab = tabControl.tab(tabControl.select(), "text")
    #print(var1)
    print(selectedTab)
    if selectedTab != "Filling":
        return
    win = tk.Toplevel()
    win.geometry("800x400")
    win.wm_title("Enter Batch Number")
    s = ttk.Style()
    s.configure('my.TButton', font=('Arial', 24))
    try:
        modbus.load_cell.write_long(0x0000, 0)
        #modbus.load_cell.write_long(0x0000, 0, False, 0)
    except:
        print("load cell error when setting tare")
    
    label = tk.Label(win, text="Batch", font=("Arial", 24), padx=20, pady=10)
    text = tk.Label(win, textvariable=batch_number, font=("Arial", 24))
    b1 = ttk.Button(win, text="1", command=lambda:batch_number.set(batch_number.get() + "1"), style='my.TButton')
    b1 = ttk.Button(win, text="1", command=lambda:batch_number.set(batch_number.get() + "1"), style='my.TButton')
    b2 = ttk.Button(win, text="2", command=lambda:batch_number.set(batch_number.get() + "2"), style='my.TButton')
    b3 = ttk.Button(win, text="3", command=lambda:batch_number.set(batch_number.get() + "3"), style='my.TButton')
    b4 = ttk.Button(win, text="4", command=lambda:batch_number.set(batch_number.get() + "4"), style='my.TButton')
    b5 = ttk.Button(win, text="5", command=lambda:batch_number.set(batch_number.get() + "5"), style='my.TButton')
    b6 = ttk.Button(win, text="6", command=lambda:batch_number.set(batch_number.get() + "6"), style='my.TButton')
    b7 = ttk.Button(win, text="7", command=lambda:batch_number.set(batch_number.get() + "7"), style='my.TButton')
    b8 = ttk.Button(win, text="8", command=lambda:batch_number.set(batch_number.get() + "8"), style='my.TButton')
    b9 = ttk.Button(win, text="9", command=lambda:batch_number.set(batch_number.get() + "9"), style='my.TButton')
    b0 = ttk.Button(win, text="0", command=lambda:batch_number.set(batch_number.get() + "0"), style='my.TButton')
    b_clear = ttk.Button(win, text="Clear", command=lambda:batch_number.set(""), style='my.TButton')
    enter = ttk.Button(win, text="Enter", command=win.destroy, style='my.TButton')

    label.grid(row=0, column=0)
    text.grid(row=0, column=1, columnspan=2)
    b1.grid(row=1, column=0, ipadx=45, ipady=18)
    b2.grid(row=1, column=1, ipadx=45, ipady=18)
    b3.grid(row=1, column=2, ipadx=45, ipady=18)
    b4.grid(row=2, column=0, ipadx=45, ipady=18)
    b5.grid(row=2, column=1, ipadx=45, ipady=18)
    b6.grid(row=2, column=2, ipadx=45, ipady=18)
    b7.grid(row=3, column=0, ipadx=45, ipady=18)
    b8.grid(row=3, column=1, ipadx=45, ipady=18)
    b9.grid(row=3, column=2, ipadx=45, ipady=18)
    b_clear.grid(row=4, column=0, ipadx=45, ipady=18)
    b0.grid(row=4, column=1, ipadx=45, ipady=18)
    enter.grid(row=4, column=2, ipadx=45, ipady=18)

#button_popup = tk.Button(cleaningtab, text="Batch", font=("Arial", 45), command=get_batch)
tabControl.bind('<<NotebookTabChanged>>', get_batch)

def take_picture():
    thread = threading.Thread(target=picture_thread)
    thread.start()

def picture_thread():
    global batch_number, cam
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H-%M-%S")
    ret, image = cam.read()
    cv2.imwrite('/home/pi/' + batch_number.get() + ' - ' + timestamp + '.jpg', image)
    # cv2.imwrite('/home/pi/' + timestamp + '.jpg', image)
    # cv2.imwrite('/home/pi/testimage.jpg', image)
    try:
        ret, image = cam.read()
        cv2.imwrite('/home/pi/' + batch_number.get() + ' - ' + timestamp + '.jpg', image)
    except:
        logging.exception("Webcam error")

def clean():
    global button_clean, cleaning
    if button_clean['text'] == "Stop":
        cleaning = 0
        button_clean['text'] = "Clean"
    else:
        cleaning = 1
        thread = threading.Thread(target=clean_thread)
        thread.start()
        button_clean['text'] = "Stop"

def prime_start(i):
    global vfd_speed, vfd_state, button_prime, priming, valve1, valve2
    start=5
    valve1, valve2 = 1, 1
    vfd_state = start
    vfd_speed = 5000
def prime_left_start(i):
    global vfd_speed, vfd_state, button_prime, priming, valve1, valve2
    start=5
    valve1, valve2 = 1, 0
    vfd_state = start
    vfd_speed = 500
    
def prime_right_start(i):
    global vfd_speed, vfd_state, button_prime, priming, valve1, valve2
    start=5
    valve1, valve2 = 0, 1
    vfd_state = start
    vfd_speed = 500

def prime_stop(i):
    global vfd_speed, vfd_state, button_prime, priming, valve1, valve2
    stop=6
    vfd_state = stop
    vfd_speed = 0
    # time.sleep(1)
    valve1, valve2 = 0, 0

def clean_thread():
    global vfd_speed, vfd_state, button_clean, cleaning, kill_all, valve1, valve2
    start=5
    stop=6
    motor_start_time = 0
    motor_start_time = time.time()

    valve1, valve2 = 1, 0

    valve1_open_time = time.time()
    valve2_open_time = 0

    vfd_state = start
    vfd_speed = 5000
    
    while time.time() - motor_start_time < 300 and cleaning == 1 and kill_all == False:
        time.sleep(0.01)
        vfd_state = start
        vfd_speed = 5000
        if time.time() - valve1_open_time > 10 and valve2_open_time == 0:
            valve1, valve2 = 1, 1
            time.sleep(0.3)
            valve1, valve2 = 0, 1
            valve1_open_time = 0
            valve2_open_time = time.time()
        if time.time() - valve2_open_time > 10 and valve1_open_time == 0:
            valve1, valve2 = 1, 1
            time.sleep(0.3)
            valve1, valve2 = 1, 0
            valve2_open_time = 0
            valve1_open_time = time.time()

    vfd_state = stop
    vfd_speed = 0
    
    motor_stop_time = time.time()
    while time.time() - motor_stop_time < 2:
        time.sleep(0.01)

    valve1, valve2 = 0, 0

    button_clean['text'] = "Clean"

button_prime = tk.Button(fillingtab, text="Main Prime", font=("Arial", 45), width=10)
button_prime.bind('<ButtonPress>', prime_start)
button_prime.bind('<ButtonRelease>', prime_stop)
button_prime_left = tk.Button(fillingtab, text="Top Up Left", font=("Arial", 20), height=2)
button_prime_left.bind('<ButtonPress>',prime_left_start)
button_prime_left.bind('<ButtonRelease>',prime_stop)
button_prime_right = tk.Button(fillingtab, text="Top Up Right", font=("Arial", 20), height=2)
button_prime_right.bind('<ButtonPress>',prime_right_start)
button_prime_right.bind('<ButtonRelease>',prime_stop)
button_clean = tk.Button(cleaningtab, text="Clean", font=("Arial", 40), command=clean, width=10, height=2, padx=10, pady=10)

def volume_change(val):
    global desired_volume
    global desired_volume_frame
    desired_volume_frame['text'] = "Target Volume - " + str(desired_volume.get())

def filling_change():
    global selected, desired_volume, mould_weight, SM_CO_GCO, H_GPH, Brie, Food_Service, SM_CO_GCO_mould, H_GPH_mould, Brie_mould, desired_volume_frame
    if selected.get() == "SM / CO / GCO":
        desired_volume.set(SM_CO_GCO)
        mould_weight = SM_CO_GCO_mould
    elif selected.get() == "H / GPH":
        desired_volume.set(H_GPH)
        mould_weight = H_GPH_mould
    elif selected.get() == "Brie":
        desired_volume.set(Brie)
        mould_weight = Brie_mould
    elif selected.get() == "Food Service":
        desired_volume.set(Food_Service)
        mould_weight = Food_Service_mould
    elif selected.get() == "Essent. Mozzarella":
        desired_volume.set(Essent_Mozz)
        mould_weight = Essent_Mozz_Mould
    elif selected.get() == "Essent. Cheddar":
        desired_volume.set(Essent_Ched)
        mould_weight = Essent_Ched_Mould    
    desired_volume_frame['text'] = "Target Volume - " + str(desired_volume.get())

r1 = ttk.Radiobutton(filling_options_frame, text='SM / CO / GCO', value='SM / CO / GCO', variable=selected, command=filling_change)
r2 = ttk.Radiobutton(filling_options_frame, text='H / GPH      ', value='H / GPH', variable=selected, command=filling_change)
r3 = ttk.Radiobutton(filling_options_frame, text='Food Service ', value='Food Service', variable=selected, command=filling_change)
r4 = ttk.Radiobutton(filling_options_frame, text='Brie         ', value='Brie', variable=selected, command=filling_change)
r5 = ttk.Radiobutton(filling_options_frame, text='Essent. Mozzarella', value='Essent. Mozzarella', variable=selected, command=filling_change)
r6 = ttk.Radiobutton(filling_options_frame, text='Essent. Cheddar', value='Essent. Cheddar', variable=selected, command=filling_change)

volume_scale = tk.Scale(desired_volume_frame, from_=0.25, to=2.5, orient='horizontal', length=510, width=20, variable=desired_volume, resolution=0.01, command=volume_change, showvalue = 0)
high_speed_scale = tk.Scale(high_speed_frame, from_=500, to=5000, orient='horizontal', length=510, width=50, variable=high_speed, showvalue = 0)
low_speed_scale = tk.Scale(low_speed_frame, from_=100, to=3000, orient='horizontal', length=510, width=50, variable=low_speed, showvalue = 0)

current_weight_frame.grid(row=0, column=0, columnspan=1, sticky="W", padx=2, pady=2)
previous_weight_frame.grid(row=0, column=1, columnspan=1, sticky="W", padx=2, pady=2)
current_batch_frame.grid(row=0, column=2, columnspan=1, sticky="W", padx=2, pady=2)
filling_options_frame.grid(row=0, column=3, rowspan=4, sticky="NE", padx=2, pady=2)
desired_volume_frame.grid(row=1, column=0, columnspan=3, sticky="W", padx=2, pady=2)
high_speed_frame.grid(row=2, column=0, columnspan=3, sticky="W", padx=2, pady=2)
low_speed_frame.grid(row=3, column=0, columnspan=3, sticky="W", padx=2, pady=2)

label_current_weight.pack()
label_previous_weight.pack()
label_current_batch.pack()

r1.pack(anchor="w", padx=5, pady=5)
r2.pack(anchor="w", padx=5, pady=5)
r3.pack(anchor="w", padx=5, pady=5)
r4.pack(anchor="w", padx=5, pady=5)
r5.pack(anchor="w", padx=5, pady=5)
r6.pack(anchor="w", padx=5, pady=5)
button_close.grid(column=0, row=1, padx=5, pady=5, sticky="SE")
#button_popup.grid(column=1, row=1, padx=5, pady=5, sticky="SE")

volume_scale.pack()
high_speed_scale.pack()
low_speed_scale.pack()

button_prime.grid(column=1, row=5, padx=5, columnspan=2, pady=1, sticky="SW")
button_prime_left.grid(column=0, row=5, padx=5, columnspan=1, pady=1, sticky="SW")
button_prime_right.grid(column=3, row=5, padx=5, columnspan=1, pady=1, sticky="SW")
button_clean.grid(column=0, row=0, padx=5, pady=11, sticky="SW")


measurements_list = []
measurements_start = time.time()
read_count = 0
scale_calibration = []

#def read_weight():
#    global read_count, measurements_list, measurements_start, display_weight, actual_mould_weight, actual_weight, publish_weight_timer
#    return(actual_weight)


def cheese_filler():
    global kill_all, cpu, csv_file, high_speed, low_speed, desired_volume, actual_weight, tare, display_weight, motor_start_time, filling_status, start_time, mould_weight, previous_label, actual_mould_weight, mqtt_client, vfd_state, vfd_speed, batch_number, valve1, valve2
    motor_stop_time = 0
    start=5
    stop=6
    mould2_fill_time = mould1_fill_time = mould2_final = mould1_final = actual_mould_weight = mould_detected = 0
    mould_weights = []
    final_mould_weight_list = []
    tabControl.tab(tabControl.select(), "text")

    while kill_all == False:
        if tabControl.tab(tabControl.select(), "text") != "Filling":
            continue
        time.sleep(0.01)
        current_weight = actual_weight
        now = datetime.now()

        if filling_status == 0:
            if actual_weight > 0 and actual_weight < mould_weight * 0.69: # nothing is on the scale
                filling_status = 0
                mould_detected = 0
                mould_weights.clear()
            elif actual_weight > mould_weight * 0.7 and actual_weight < mould_weight * 1.3 : # a mould is on the scale
                if mould_detected == 0:
                    mould_detected = time.time()
                    take_picture()
                elif time.time() - mould_detected > 2 and len(mould_weights) > 20:
                    if actual_weight > mould_weight * 0.7 and actual_weight < mould_weight * 1.3 : # after 2 seconds, check the weight again. If the mould is still there, start filling
                        filling_status = 1
                        actual_mould_weight = sum(mould_weights) / len(mould_weights)
                        logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
                        " Current Weight = " + str(actual_weight) + \
                        ", Mould Weight = " + str(actual_mould_weight) + \
                        ", Filling Status = " + str(filling_status) + \
                        ", Flavour = " + selected.get() + \
                        ", Batch Number = " + batch_number.get())
                        take_picture()
                        if selected.get() == "Brie":
                            valve1, valve2 = 1, 1
                            logging.info("Valves Open both valves")
                        else:
                            valve1, valve2 = 1, 0
                            logging.info("Valves Open valve 1")

                    else:
                        mould_detected = 0
                else:
                    mould_weights.append(actual_weight)
                    # waiting waiting for 2 seconds since mould detected
            else:
                filling_status = 0
                mould_detected = 0

        elif filling_status == 1:
            filling_status = 2
            logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
            " Current Weight = " + str(actual_weight) + \
            ", Mould Weight = " + str(actual_mould_weight) + \
            ", Filling Status = " + str(filling_status) + \
            ", Flavour = " + selected.get() + \
            ", Batch Number = " + batch_number.get())
            if motor_start_time == 0:
                motor_start_time = time.time()
                vfd_state = start
                vfd_speed = int(high_speed.get())
                logging.info("Start VFD at speed " + str(high_speed.get()))

        elif filling_status == 2:
            if actual_weight - actual_mould_weight < float(desired_volume.get()) - 0.2: #keep filling at high speed
                filling_status = 2
                vfd_state = start
                vfd_speed = int(high_speed.get())
            elif actual_weight - actual_mould_weight > float(desired_volume.get()) - 0.2: #set filling speed to low
                filling_status = 3
                vfd_state = start
                vfd_speed = int(low_speed.get())
                logging.info("Slow VFD to speed " + str(low_speed.get()))
                logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
                " Current Weight = " + str(actual_weight) + \
                ", Mould Weight = " + str(actual_mould_weight) + \
                ", Filling Status = " + str(filling_status) + \
                ", Flavour = " + selected.get() + \
                ", Batch Number = " + batch_number.get())
                
        elif filling_status == 3:
            if actual_weight - actual_mould_weight > float(desired_volume.get()):
                vfd_state = stop
                vfd_speed = 0
                if motor_stop_time == 0:
                    motor_stop_time = time.time()
                    final_mould_weight_list.clear()
                elif time.time() - motor_stop_time > 0.2:
                    valve1, valve2 = 0, 0
                    logging.info("Valves Close both valves")
                    if len(final_mould_weight_list) < 10:
                        final_mould_weight_list.append(actual_weight - actual_mould_weight)
                        logging.info("Measurement Mould 1 reading " + str(len(final_mould_weight_list)) + " is " + str(actual_weight))
                    else:
                        filling_status = 4
                        mould1_final = sum(final_mould_weight_list) / len(final_mould_weight_list)
                        logging.info("Weights Mould 1 final weight = " + str(mould1_final))
                        mould1_fill_time = time.time() - motor_start_time
                        logging.info("FillTime Mould 1 Fill Time = " + str(mould1_fill_time))
                        previous_label.set(str(round(mould1_final,3)))
                        logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
                        " Current Weight = " + str(actual_weight) + \
                        ", Mould Weight = " + str(actual_mould_weight) + \
                        ", Filling Status = " + str(filling_status) + \
                        ", Flavour = " + selected.get() + \
                        ", Batch Number = " + batch_number.get())
            else:
                if motor_stop_time != 0 and time.time() - motor_stop_time > 0.5:
                    vfd_state = start
                    vfd_speed = int(low_speed.get())
                    motor_stop_time = 0

        elif filling_status == 4:
            if selected.get() != "Brie":
                filling_status = 6
                motor_stop_time = 0
                motor_start_time = 0
                logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
                " Current Weight = " + str(current_weight) + \
                ", Mould Weight = " + str(actual_mould_weight) + \
                ", Filling Status = " + str(filling_status) + \
                ", Flavour = " + selected.get() + \
                ", Batch Number = " + batch_number.get())
                take_picture()
            else:
                filling_status = 5
                mould2_fill_time = 0
                mould2_final = 0
                logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
                " Current Weight = " + str(current_weight) + \
                ", Mould Weight = " + str(actual_mould_weight) + \
                ", Filling Status = " + str(filling_status) + \
                ", Flavour = " + selected.get() + \
                ", Batch Number = " + batch_number.get())
            
                    
        elif filling_status == 5:
            if actual_weight < mould_weight: # The completed moulds have been removed from the machine
                mould_weights = []
                now = datetime.now()
                dt_string = now.strftime("%Y-%m-%d %H-%M-%S")
                csv_data = [dt_string, batch_number.get(), str(actual_mould_weight), selected.get(), desired_volume.get(), high_speed.get(), low_speed.get(), mould1_final, mould1_fill_time, mould2_final, mould2_fill_time, cpu.temperature]
                csv_record(csv_data)
                csv_file.writerow(csv_data)
                motor_stop_time = 0
                motor_start_time = 0
                mould_detected = 0
                filling_status = 0
                actual_mould_weight = 0
                tare = 0
                try:
                    mqtt_client.publish("FillingMachine/Completed-Mould1FinalWeight", mould1_final)
                    mqtt_client.publish("FillingMachine/Completed-Mould1FillTime", mould1_fill_time)
                    mqtt_client.publish("FillingMachine/Completed-Mould2FinalWeight", mould2_final)
                    mqtt_client.publish("FillingMachine/Completed-Mould2FillTime", mould2_fill_time)
                    mqtt_client.publish("FillingMachine/Completed-DesiredVolume", desired_volume.get())
                    mqtt_client.publish("FillingMachine/Completed-HighSpeed", high_speed.get())
                    mqtt_client.publish("FillingMachine/Completed-LowSpeed", low_speed.get())
                    mqtt_client.publish("FillingMachine/Completed-BatchNumber", batch_number.get())
                except Exception as e:
                    logging.exception("There was an MQTT error - " + str(e))
                logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
                " Current Weight = " + str(current_weight) + \
                ", Mould Weight = " + str(actual_mould_weight) + \
                ", Filling Status = " + str(filling_status) + \
                ", Flavour = " + selected.get() + \
                ", Batch Number = " + batch_number.get())

        elif filling_status == 6: # ready to start filling the second mould
            filling_status = 7
            valve1, valve2 = 0, 1
            logging.info("Open valve 2")
            tare = actual_weight # this is the weight of the tray, full mould 1 and empty mould 2
            motor_start_time = time.time()
            vfd_state = start
            vfd_speed = int(high_speed.get())
            logging.info("Start VFD at speed " + str(high_speed.get()))
            logging.info("Filler Time = " + str(time.time()) + \
            " Current Weight = " + str(actual_mould_weight) + \
            ", Filling Status = " + str(filling_status) + \
            ", Flavour = " + selected.get() + \
            ", Batch Number = " + batch_number.get())

        elif filling_status == 7:
            if actual_weight - tare < float(desired_volume.get()) - 0.2:
                vfd_state = start
                vfd_speed = int(high_speed.get())
            else:
                vfd_state = start
                vfd_speed = int(low_speed.get())
                logging.info("Slow VFD to speed " + str(low_speed.get()))
                filling_status = 8
                logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
                " Current Weight = " + str(actual_weight) + \
                ", Mould Weight = " + str(tare) + \
                ", Filling Status = " + str(filling_status) + \
                ", Flavour = " + selected.get() + \
                ", Batch Number = " + batch_number.get())
                
        elif filling_status == 8:
            
            if actual_weight - tare > float(desired_volume.get()):
                vfd_state = stop
                vfd_speed = 0
                if motor_stop_time == 0:
                    motor_stop_time = time.time()
                    final_mould_weight_list.clear()
                elif time.time() - motor_stop_time > 0.2:
                    valve1, valve2 = 0, 0
                    logging.info("Close both valves")
                    if len(final_mould_weight_list) < 10:
                        final_mould_weight_list.append(actual_weight - tare)
                    else:
                        mould2_final = sum(final_mould_weight_list) / len(final_mould_weight_list)
                        previous_label.set(previous_label.get() + ", " + str(round(mould2_final,3)))
                        mould2_fill_time = time.time() - motor_start_time
                        logging.info("Weights Mould 2 final weight = " + str(mould2_final))
                        logging.info("FillTime Mould 2 Fill Time = " + str(mould2_fill_time))
                        filling_status = 9
                        logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
                        " Current Weight = " + str(actual_weight) + \
                        ", Mould Weight = " + str(tare) + \
                        ", Filling Status = " + str(filling_status) + \
                        ", Flavour = " + selected.get() + \
                        ", Batch Number = " + batch_number.get())
                        take_picture()
            else:
                if motor_stop_time != 0 and time.time() - motor_stop_time > 0.5:
                    valve1, valve2 = 0, 1
                    vfd_state = start
                    vfd_speed = int(low_speed.get())
                    motor_stop_time = 0

        elif filling_status == 9:
            if time.time() - motor_stop_time > 1:
                filling_status = 5
                logging.info("Filler Time = " + now.strftime("%Y-%m-%d %H-%M-%S") + \
                " Current Weight = " + str(current_weight) + \
                ", Mould Weight = " + str(actual_mould_weight) + \
                ", Filling Status = " + str(filling_status) + \
                ", Flavour = " + selected.get() + \
                ", Batch Number = " + batch_number.get())

filling_change()

vfd_state = 6
vfd_speed = 0

# def vfd_monitor():
#     global vfd_state, vfd_speed, kill_all
#     current_state = current_speed = 0
#     while kill_all == False:
#         try:
#             current_state = modbus.turny_boi.read_register(0x1E02)
#         except Exception as e:
#             logging.exception("VDF_Monitor1 MODBUS error - " + str(e))
#         try:
#             current_speed = modbus.turny_boi.read_register(0x1E01)
#         except Exception as e:
#             logging.exception("VDF_Monitor2 MODBUS Error - " + str(e))
#         if (vfd_state == 5 and current_state == 11):
#             # logging.info("state is correct: " + str(current_state))
#             pass
#         elif (vfd_state == 6 and current_state == 1):
#             # logging.info("state is correct: " + str(current_state))
#             pass
#         else:
#             try:
#                 logging.info("vfd state is wrong: " + str(current_state))
#                 modbus.turny_boi.write_register(0x1E00, vfd_state)
#             except Exception as e:
#                 logging.exception("VDF_Monitor3 MODBUS error - " + str(e))
        
#         if (vfd_speed != current_speed):
#             try:
#                 modbus.turny_boi.write_register(0x1E01, vfd_speed)
#             except Exception as e:
#                 logging.exception("VDF_Monitor4 MODBUS error - " + str(e))
#         time.sleep(0.01)
#     modbus.turny_boi.write_register(0x1E01, 0)
#     modbus.turny_boi.write_register(0x1E00, 6)
    
# vfd_monitoring = threading.Thread(target=vfd_monitor)
# vfd_monitoring.start()

def monitoring_thread():
    global mqtt_client, cpu, kill_all, high_speed, low_speed, desired_volume, actual_weight, display_weight, filling_status, mould_weight, actual_mould_weight, vfd_state, vfd_speed, tare
    while kill_all == False:
        try:
            mqtt_client.publish("FillingMachine/CPUTemp", cpu.temperature)
            mqtt_client.publish("FillingMachine/HighSpeed", high_speed.get())
            mqtt_client.publish("FillingMachine/LowSpeed", low_speed.get())
            mqtt_client.publish("FillingMachine/DesiredVolume", desired_volume.get())
            mqtt_client.publish("FillingMachine/ActualWeight", actual_weight)
            mqtt_client.publish("FillingMachine/DisplayWeight", display_weight.get())
            mqtt_client.publish("FillingMachine/FillingStatus", filling_status)
            mqtt_client.publish("FillingMachine/MouldWeight", mould_weight)
            mqtt_client.publish("FillingMachine/ActualMouldWeight", actual_mould_weight)
            mqtt_client.publish("FillingMachine/Tare", tare)
            mqtt_client.publish("FillingMachine/VFDState", vfd_state)
            mqtt_client.publish("FillingMachine/VFDSpeed", vfd_speed)
        except Exception as e:
            logging.exception("MQTT error - " + str(e))
        time.sleep(0.1)

def csv_record(csv_data):
    global header
    now = datetime.now()
    # dd/mm/YY H:M:S
    date_string = now.strftime("%Y-%m-%d")
    if (exists('/home/pi/' + date_string + '.csv')):
        with open('/home/pi/' + date_string + '.csv', mode="a") as csv_record_file:
            writer = csv.writer(csv_record_file)
            writer.writerow(csv_data)
            #writer.close()
    else:
        with open('/home/pi/' + date_string + '.csv', mode="w") as csv_record_file:
            writer = csv.writer(csv_record_file)
            writer.writerow(header)
            writer.writerow(csv_data)
            #writer.close()
    
def modbus_thread():
    global vfd_state, vfd_speed, lc_que, valve1, valve2, read_count, measurements_list, measurements_start, tare, display_weight, actual_mould_weight, actual_weight, publish_weight_timer
    current_state = current_speed = 0
    # valve_time = time.time()
    valve1_state = valve1
    valve2_state = valve2
    while kill_all == False:

#--- VFD ---
        try:
            current_state = modbus.turny_boi.read_register(0x1E02)
        except Exception as e:
            logging.exception("VDF_Monitor1 MODBUS error - " + str(e))
        try:
            current_speed = modbus.turny_boi.read_register(0x1E01)
        except Exception as e:
            logging.exception("VDF_Monitor2 MODBUS Error - " + str(e))
        if (vfd_state == 5 and current_state == 11):
            # logging.info("state is correct: " + str(current_state))
            pass
        elif (vfd_state == 6 and current_state == 1):
            # logging.info("state is correct: " + str(current_state))
            pass
        else:
            try:
                logging.info("vfd state is wrong: " + str(current_state))
                modbus.turny_boi.write_register(0x1E00, vfd_state)
            except Exception as e:
                logging.exception("VDF_Monitor3 MODBUS error - " + str(e))
        
        if (vfd_speed != current_speed):
            try:
                modbus.turny_boi.write_register(0x1E01, vfd_speed)
            except Exception as e:
                logging.exception("VDF_Monitor4 MODBUS error - " + str(e))

#--- VALVES ---        
        if valve1 != valve1_state or valve2 != valve2_state:
            # time.sleep(0.05)
            if valve1 == 0 and valve2 == 0:
                try:
                    modbus.valves.write_register(0x0080, 0)
                except Exception as e:
                    logging.exception("Valves1 MODBUS error - " + str(e))
                    # time.sleep(0.2)
                    continue
            if valve1 == 1 and valve2 == 0:
                try:
                    modbus.valves.write_register(0x0080, 1)
                except Exception as e:
                    logging.exception("Valves2 MODBUS error - " + str(e))
                    # time.sleep(0.2)
                    continue
            if valve1 == 0 and valve2 == 1:
                try:
                    modbus.valves.write_register(0x0080, 2)
                except Exception as e:
                    logging.exception("Valves3 MODBUS error - " + str(e))
                    # time.sleep(0.2)
                    continue
            if valve1 == 1 and valve2 == 1:
                try:
                    modbus.valves.write_register(0x0080, 3)
                except Exception as e:
                    logging.exception("Valves4 MODBUS error - " + str(e))
                    # time.sleep(0.2)
                    continue
            valve1_state = valve1
            valve2_state = valve2
            # time.sleep(0.2)

#--- LOADCELL ---        
        selectedTab = tabControl.tab(tabControl.select(), "text")
        if selectedTab == "Filling":
            try:
                lc_reading = modbus.load_cell.read_long(0x0000, 3, False, 0)
                if (lc_reading > 4000000000):
                    lc_reading = lc_reading - 4294967295
                lc_que.pop()
                lc_que.appendleft(lc_reading)
                av_sum = 0
                for i in range(que_length): 
                    av_sum = av_sum + lc_que[i]
                actual_weight = (av_sum / que_length) / 1000
                logging.info("Measurements: " + str(lc_que) + "Calculated Value = " + str(actual_weight))
            except Exception as e:
                # print("load cell clash")
                logging.exception("LOADCELL MODBUS Load Cell Read Error - " + str(e))
            calculated_weight = actual_weight - actual_mould_weight - tare
            display_weight.set(round(calculated_weight,3))
            mqtt_client.publish("FillingMachine/lc_reading", lc_reading/1000)
            mqtt_client.publish("FillingMachine/actual_weight", actual_weight)
        else:
            time.sleep(0.01)   
    modbus.turny_boi.write_register(0x1E01, 0)
    modbus.turny_boi.write_register(0x1E00, 6)
     

valve_and_loadcell = threading.Thread(target=modbus_thread)
valve_and_loadcell.start()    
monitoring = threading.Thread(target=monitoring_thread)
monitoring.start()
cheese_maker = threading.Thread(target=cheese_filler)
cheese_maker.start()
# Run forever!
root.mainloop()
