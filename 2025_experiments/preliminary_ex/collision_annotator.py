import time
import csv
from pynput import keyboard
import platform
import os
import simpleaudio as sa
import threading

system = platform.system()
if system in ["Darwin", "Linux"] and sa is not None:
    try:
        SOUND_FILE = "se.wav"
        wave_obj = sa.WaveObject.from_wave_file(SOUND_FILE)
        print(wave_obj)
    except Exception as e:
        print("Failed to load sound file:", e)
        wave_obj = None
else:
    wave_obj = None

# Global variables
recording_state = False  # False: Not started, True: Started
experiment_state = False  # False: Experiment not started, True: Experiment started
CSV_FILENAME = time.strftime("%Y%m%d-%H%M%S") + "_annotations.csv"
FIELDNAMES = ['event', 'timestamp']

def beep():
    """
    Play a beep sound based on the operating system.
    """
    sys_platform = platform.system()
    if sys_platform == "Windows":
        import winsound
        winsound.Beep(1000, 200)  # 1000Hz for 200ms
    elif sys_platform in ["Darwin", "Linux"] and wave_obj is not None:
        wave_obj.play()
    else:
        print('\a', end='', flush=True)  # Fallback terminal bell

def record_annotation(event_type):
    """
    Record an annotation with the event type and the current timestamp,
    and immediately append it to the CSV file.
    """
    timestamp = time.time()  # Unix timestamp
    header_needed = not os.path.exists(CSV_FILENAME) or os.path.getsize(CSV_FILENAME) == 0

    with open(CSV_FILENAME, 'a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        if header_needed:
            writer.writeheader()
        writer.writerow({'event': event_type, 'timestamp': timestamp})

    print(f"{event_type.capitalize()} recorded at {timestamp}")
    beep()

def end_experiment():
    global experiment_state
    if experiment_state:
        record_annotation("experiment_end")
        experiment_state = False

def on_press(key):
    """
    Handle key press events.

    - Space key starts the experiment and automatically ends it after 5 minutes.
    - Shift key starts recording.
    - Control key ends recording.
    - 'q' key quits the application (only if there is no ongoing recording).
    """
    global recording_state, experiment_state
    try:
        if key == keyboard.Key.space:
            if not experiment_state:
                record_annotation("experiment_start")
                experiment_state = True
                threading.Timer(300, end_experiment).start()  # Automatically end experiment after 5 min
            else:
                print("Experiment already started. It will automatically end in 5 minutes.")
        elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            if not recording_state:
                record_annotation("start")
                recording_state = True
            else:
                print("Recording already started. Press Control key to end.")
        elif key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            if recording_state:
                record_annotation("end")
                recording_state = False
            else:
                print("Recording hasn't started yet. Press Shift key to start.")
        elif key.char == 'q':
            if recording_state:
                print("Cannot quit: there is an incomplete start event. Press Control key to end.")
            else:
                return False  # Stop the listener
    except AttributeError:
        pass  # Ignore special keys without a char attribute

print("Press Space to start the experiment (automatically ends in 5 min), Shift to start recording, Control to end recording, and 'q' to quit.")
with keyboard.Listener(on_press=on_press) as listener:
    listener.join()

print(f"Annotations have been recorded in {CSV_FILENAME}")
