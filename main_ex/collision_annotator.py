import time
import csv
from pynput import keyboard
import platform
import os
import simpleaudio as sa
import threading

# Setup sound for macOS/Linux if available.
system = platform.system()
if system in ["Darwin", "Linux"] and sa is not None:
    try:
        SOUND_FILE = "se.wav"
        wave_obj = sa.WaveObject.from_wave_file(SOUND_FILE)
    except Exception as e:
        print("Failed to load sound file:", e)
        wave_obj = None
else:
    wave_obj = None

# Global states
experiment_state = False  # Indicates whether the experiment is ongoing
waiting_for_human_id = False  # Prevents new collision events until input is complete

# CSV configuration: add a new column "human_id"
CSV_FILENAME = time.strftime("%Y%m%d-%H%M%S") + "_annotations.csv"
FIELDNAMES = ['event', 'timestamp', 'human_id']

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

def record_annotation(event_type, human_id="", timestamp=None):
    """
    Record an annotation with event type, timestamp, and human_id,
    and immediately append it to the CSV file.
    """
    if timestamp is None:
        timestamp = time.time()
    header_needed = not os.path.exists(CSV_FILENAME) or os.path.getsize(CSV_FILENAME) == 0

    with open(CSV_FILENAME, 'a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        if header_needed:
            writer.writeheader()
        writer.writerow({'event': event_type, 'timestamp': timestamp, 'human_id': human_id})

    print(f"{event_type.capitalize()} recorded at {timestamp} (human_id: {human_id})")
    beep()

def end_experiment():
    global experiment_state
    if experiment_state:
        record_annotation("experiment_end")
        experiment_state = False

def prompt_for_human_id():
    """
    Prompt the user to input the standing human id.
    Blocks until a valid input (1-8) is provided, then returns it.
    """
    while True:
        user_input = input("Enter standing human id (1-8): ").strip()
        if user_input.isdigit() and 1 <= int(user_input) <= 8:
            return user_input
        else:
            print("Invalid ID entered. Please enter a number between 1 and 8.")

def handle_collision(collision_timestamp):
    """
    Handles the collision event:
      1. Prompts for human id input.
      2. Records the collision event with the original collision timestamp.
    """
    human_id = prompt_for_human_id()
    record_annotation("collision", human_id=human_id, timestamp=collision_timestamp)
    global waiting_for_human_id
    waiting_for_human_id = False

def on_press(key):
    """
    - Space: Start the experiment (if not already started).
    - Shift (any shift key): Record a collision event. This captures the timestamp and then
      prompts for the human id. No new collision is accepted until a valid human id is entered.
    - 'q': Quit the application (only allowed if experiment is not ongoing).
    """
    global experiment_state, waiting_for_human_id
    try:
        if key == keyboard.Key.space:
            if not experiment_state:
                record_annotation("experiment_start")
                experiment_state = True
                threading.Timer(300, end_experiment).start()
            else:
                print("Experiment already started.")
        elif key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            if waiting_for_human_id:
                print("Waiting for previous human id input. Please complete that entry before recording a new collision.")
            else:
                waiting_for_human_id = True
                # Capture the collision timestamp at the moment Shift is pressed.
                collision_timestamp = time.time()
                # Start a thread to handle the collision input so as not to block the listener.
                threading.Thread(target=handle_collision, args=(collision_timestamp,), daemon=True).start()
        elif hasattr(key, 'char') and key.char == 'q':
            if experiment_state:
                print("Cannot quit while experiment is ongoing.")
            else:
                return False  # Stop the listener
    except AttributeError:
        pass  # Ignore special keys without a char attribute

print("Press Space to start the experiment.")
print("Press Shift to record a collision event (you will be prompted for the human id).")
print("Press 'q' to quit (only allowed if the experiment is not ongoing).")
with keyboard.Listener(on_press=on_press) as listener:
    listener.join()

print(f"Annotations have been recorded in {CSV_FILENAME}")
