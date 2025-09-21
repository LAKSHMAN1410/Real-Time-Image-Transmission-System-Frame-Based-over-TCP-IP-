import tkinter as tk
from tkinter import messagebox, filedialog
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import cv2
from PIL import Image, ImageTk
import threading
import datetime
import os
import time
import socket
import multiprocessing
import sys
import subprocess
import shutil # Import shutil for folder deletion
import random

# --- Global/Configuration Variables ---
TRANSMITTER_NAME = "TX2" # Set to TX1, TX2, TX3, or TX4 as per request
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
single_image_folder = os.path.join(BASE_DIR, f"{TRANSMITTER_NAME}_sent_images")
frames_output_folder = os.path.join(BASE_DIR, f"{TRANSMITTER_NAME}_sent_frames")

jpeg_quality = 40 # Base JPEG quality for single/chosen images
header_size = 10 # This remains constant as the size of your header
cols = 20 # Number of columns for frame organization (used in header)
HOST = '192.168.196.105' # Ensure this IP is correct and reachable
PORT = 49697 # Ensure this port is open and the Receiver is listening on it

# --- Display Size Adjustment ---
# Increased size for better visibility - these sizes will now act as maximums
DISPLAY_AREA_WIDTH = 820
DISPLAY_AREA_HEIGHT = 480 # Adjusted height to be more rectangular for dashboard feel

# Ensure output directories exist
os.makedirs(single_image_folder, exist_ok=True)
os.makedirs(frames_output_folder, exist_ok=True)

class TransmitterApp:
    def __init__(self, master):
        self.master = master
        master.title(f"📡 {TRANSMITTER_NAME} Image Transmission Dashboard")
        master.state('zoomed')
        master.protocol("WM_DELETE_WINDOW", self.exit_application)

        # --- UI Layout Configuration Constants ---
        self.PADDING_X = 15
        self.PADDING_Y = 0.05
        self.BORDER_WIDTH = 0.5
        self.RELIEF_STYLE = "flat"
        self.WIDGET_PAD_Y = 0.4
        self.SIDEBAR_BUTTON_PAD_X = 10 # Increased for better spacing
        self.SIDEBAR_WIDTH = 250 # Fixed width for sidebar

        # --- Application State Variables ---
        self.camera_running = False
        self.is_camera_display_on = True
        self.cap = None
        self.last_captured_filename = None
        self.captured_image_queue = multiprocessing.Queue()
        self.last_live_camera_frame = None

        self.is_continuous_capture_active = False
        self.continuous_capture_thread = None
        self.continuous_capture_button = None
        self.continuous_capture_interval_ms = 5000

        self.is_timer_capture_active = False
        self.timer_capture_thread = None
        self.timer_capture_button = None
        self.timer_capture_interval_ms = 5000
        self.timer_count = 0
        self.timer_start_time = None
        self.timer_cycle_active_duration_seconds = 15 * 60
        self.timer_cycle_sleep_duration_seconds = 15 * 60
        self.timer_cycle_end_time = None
        self.timer_next_active_time = None

        # --- GUI Elements References (for dynamic updates) ---
        self.live_camera_feed_label = None
        self.captured_img_label = None
        self.byte_rate_label = None
        self.continuous_capture_status_label = None
        # Removed: self.transmission_progress_label = None (no longer exists)
        self.timer_capture_status_label = None

        # MODIFIED: Initial value and range for data_size_var (55 to 100)
        self.data_size_var = tk.IntVar(value=75) # Set initial value within new range

        # Initialize GUI components
        self._create_widgets()
        self._start_camera_stream() # Attempt to start camera stream on app launch

    # --- Backend/Core Functionality (Unchanged) ---

    def get_unique_image_name(self, prefix="live"):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        return f"{TRANSMITTER_NAME}_{prefix}_img_{timestamp}.jpg"

    def connect_to_receiver(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            self._log_event(f"Attempting to connect to {HOST}:{PORT}...")
            s.connect((HOST, PORT))
            s.sendall(TRANSMITTER_NAME.encode().ljust(50, b'\x00'))
            self._log_event(f"✅ Connected to Receiver: {HOST}:{PORT}")
            return s
        except socket.timeout:
            self.master.after(0, messagebox.showerror, "Connection Error", f"Connection to receiver timed out ({HOST}:{PORT}).")
            self._log_event(f"❌ Connection timed out to {HOST}:{PORT}")
            return None
        except ConnectionRefusedError:
            self.master.after(0, messagebox.showerror, "Connection Error", f"Connection refused by receiver ({HOST}:{PORT}). Is the Receiver application running and listening?")
            self._log_event(f"❌ Connection refused by {HOST}:{PORT}")
            return None
        except Exception as e:
            self.master.after(0, messagebox.showerror, "Connection Error", f"Failed to connect to receiver: {e}")
            self._log_event(f"❌ Connection failed: {e}")
            return None

    def generate_frames_from_file(self, file_path):
        file_filename = os.path.basename(file_path)
        try:
            with open(file_path, 'rb') as f:
                file_bytes = f.read()
        except FileNotFoundError:
            self._log_event(f"ERROR: File not found for frame generation: {file_path}")
            return None, 0, None

        total_frame_size = self.data_size_var.get()
        chunk_size = total_frame_size - header_size

        # This check is still valid and important
        if chunk_size <= 0:
            self._log_event(f"ERROR: Calculated chunk size ({chunk_size} bytes) is zero or negative (total frame size {total_frame_size} - header size {header_size}). Aborting frame generation. Please set 'Data Size' higher than {header_size}.")
            self.master.after(0, messagebox.showerror, "Configuration Error", f"Calculated image data chunk size is too small or negative. Please set 'Data Size (Bytes per chunk)' to be greater than {header_size} bytes.")
            return None, 0, None

        total_frames = (len(file_bytes) + chunk_size - 1) // chunk_size
        file_frame_dir = os.path.join(frames_output_folder, os.path.splitext(file_filename)[0] + "_" + datetime.datetime.now().strftime("%H%M%S_%f"))
        os.makedirs(file_frame_dir, exist_ok=True)

        self._log_event(f"Generating frames: Total Frame Size requested: {total_frame_size} bytes (Header: {header_size} bytes, Image Data Chunk: {chunk_size} bytes).")

        for i in range(total_frames):
            chunk_start = i * chunk_size
            chunk_end = (i + 1) * chunk_size
            raw_chunk = file_bytes[chunk_start:chunk_end]
            chunk = raw_chunk + b'\x00' * (chunk_size - len(raw_chunk))

            row_idx, col_idx = i // cols, i % cols
            header = (
                i.to_bytes(2, 'big') +
                row_idx.to_bytes(2, 'big') +
                col_idx.to_bytes(2, 'big') +
                total_frames.to_bytes(2, 'big') +
                b'\x00\x00'
            )
            frame_content = header + chunk
            expected_size = header_size + chunk_size
            if len(frame_content) != expected_size:
                self._log_event(f"WARN: Generated frame {i} size mismatch! Expected {expected_size}, got {len(frame_content)}")

            frame_filename = f"frame_{i:04d}_{row_idx}_{col_idx}.bin"
            with open(os.path.join(file_frame_dir, frame_filename), 'wb') as f:
                f.write(frame_content)
        self._log_event(f"Generated {total_frames} frames for {os.path.basename(file_filename)} in {file_frame_dir}. Each frame is {total_frame_size} bytes.")
        return file_filename, total_frames, file_frame_dir

    def send_data_to_receiver_threaded(self, path_to_send, silent_mode=False):
        if not path_to_send or not os.path.exists(path_to_send):
            if not silent_mode:
                self.master.after(0, messagebox.showwarning, "Transmission Error", "File does not exist to transmit.")
            self._log_event(f"Attempted to send non-existent file: {path_to_send}")
            return
        threading.Thread(target=self._send_data_task, args=(path_to_send, silent_mode,), daemon=True).start()

    def _send_data_task(self, file_path, silent_mode):
        conn = None
        file_filename, total_frames, file_frame_dir = self.generate_frames_from_file(file_path)
        if file_filename is None:
            if not silent_mode:
                self.master.after(0, messagebox.showerror, "Transmission Error", f"Failed to generate frames for {os.path.basename(file_path)}. Transmission aborted.")
            self._log_event(f"Transmission of {os.path.basename(file_path)} aborted: Frame generation failed.")
            # Removed: Update label on frame generation failure
            # current_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # self.master.after(0, self.transmission_progress_label.config, {"text": f"Frame Gen Failed!\n{current_dt}", "bootstyle": "danger"})
            return

        # Removed: Indicate activity on transmission_progress_label
        # self.master.after(0, self.transmission_progress_label.config, {"bootstyle": "info"}) 

        try:
            self._log_event(f"Starting transmission of {os.path.basename(file_path)} (Total Frames: {total_frames})...")
            conn = self.connect_to_receiver()
            if not conn:
                # Removed: Update label on connection failure
                # current_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # self.master.after(0, self.transmission_progress_label.config, {"text": f"Connection Failed!\n{current_dt}", "bootstyle": "danger"})
                self._log_event(f"Transmission of {os.path.basename(file_path)} aborted due to connection failure.")
                return

            conn.sendall(file_filename.encode().ljust(100, b'\x00'))
            conn.sendall(self.data_size_var.get().to_bytes(4, 'big'))
            self._log_event(f"Sent filename '{file_filename}' and total frame size '{self.data_size_var.get()}' for {os.path.basename(file_path)}.")

            for i in range(total_frames):
                row_idx, col_idx = i // cols, i % cols
                frame_file = os.path.join(file_frame_dir, f"frame_{i:04d}_{row_idx}_{col_idx}.bin")
                if not os.path.exists(frame_file):
                    if not silent_mode:
                        self.master.after(0, messagebox.showerror, "Transmission Error", f"Missing frame file during transmission: {os.path.basename(frame_file)}")
                    self._log_event(f"Transmission Failed: Missing frame {os.path.basename(frame_file)}. Aborting.")
                    break
                with open(frame_file, 'rb') as f:
                    conn.sendall(f.read())
                

            else: # This block executes if the loop completes without a 'break'
                if not silent_mode:
                    self.master.after(0, messagebox.showinfo, "Transmission Complete", f"Successfully sent: {os.path.basename(file_path)}")
                self.master.after(0, self._log_event, f"Transmission Complete: {os.path.basename(file_path)}")
                # Removed: Update text with new status, and bootstyle
                # current_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # self.master.after(0, self.transmission_progress_label.config, {"text": f"Transmission Successful!\n{current_dt}", "bootstyle": "success"})
                
                if silent_mode and (self.is_timer_capture_active or self.is_continuous_capture_active):
                    if self.is_timer_capture_active:
                        self.timer_count += 1

        except Exception as e:
            if not silent_mode:
                self.master.after(0, messagebox.showerror, "Transmission Error", f"Failed to send {os.path.basename(file_path)}: {e}")
            self.master.after(0, self._log_event, f"❌ Transmission Error for {os.path.basename(file_path)}: {e}")
            # Removed: Update text for error with current date/time, and change bootstyle to danger
            # current_dt = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # self.master.after(0, self.transmission_progress_label.config, {"text": f"Transmission Failed!\n{current_dt}", "bootstyle": "danger"})
            if "WinError 10053" in str(e):
                self.master.after(0, self._log_event, "Possible cause: Receiver closed connection unexpectedly or firewall/antivirus interference.")
            if file_frame_dir and os.path.exists(file_frame_dir):
                self._log_event(f"Cleaning up partially created/failed frames directory: {file_frame_dir}")
                shutil.rmtree(file_frame_dir)
        finally:
            if conn:
                conn.close()
                self._log_event("Connection closed after transmission attempt.")

    def update_live_camera_feed_display(self, *args): # Added *args for compatibility with after method
        if not self.camera_running or not self.cap or not self.cap.isOpened() or not self.is_camera_display_on:
            self.live_camera_feed_label.config(image='')
            return

        ret, frame = self.cap.read()
        if not ret:
            self._log_event("Failed to read frame from camera for display. Attempting to stop display.")
            self._pause_camera_display()
            return

        self.last_live_camera_frame = frame

        self._display_image_in_label(self.live_camera_feed_label, frame, (DISPLAY_AREA_WIDTH, DISPLAY_AREA_HEIGHT))

        if self.is_camera_display_on:
            self.master.after(15, self.update_live_camera_feed_display)

    def _start_camera_stream(self):
        if self.cap and self.cap.isOpened():
            self._log_event("Camera already streaming.")
            self.is_camera_display_on = True
            self.update_live_camera_feed_display()
            return True

        self.cap = cv2.VideoCapture(0)
        if self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, DISPLAY_AREA_WIDTH)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, DISPLAY_AREA_HEIGHT)
            self.camera_running = True
            self.is_camera_display_on = True
            self.update_live_camera_feed_display()
            self._log_event("Camera Stream Started.")
            return True
        else:
            self._log_event("ERROR: Camera failed to start stream.")
            self.camera_running = False
            self.is_camera_display_on = False
            if self.cap: self.cap.release()
            self.cap = None
            self.live_camera_feed_label.config(image='', text="📸 Live Camera Feed\n(Camera Off)")
            return False

    def _stop_camera_stream(self):
        if not self.cap or not self.cap.isOpened():
            return

        self.camera_running = False
        self.is_camera_display_on = False
        self.cap.release()
        self.cap = None
        self.last_live_camera_frame = None
        self.master.after(0, self.live_camera_feed_label.config, image='', text="📸 Live Camera Feed\n(Camera Off)")
        self._log_event("Camera Stream Stopped.")

    def _pause_camera_display(self):
        if self.is_camera_display_on:
            self.is_camera_display_on = False
            self.master.after(0, self.live_camera_feed_label.config, image='', text="📸 Live Camera Feed\n(Display Off - Sleeping)")
            self._log_event("Camera display paused.")

    def _resume_camera_display(self):
        if not self.is_camera_display_on and self.camera_running:
            self.is_camera_display_on = True
            self.master.after(0, self.update_live_camera_feed_display)
            self._log_event("Camera display resumed.")

    def start_camera(self):
        if self._start_camera_stream():
            messagebox.showinfo("Camera Status", "Camera started successfully.")
        else:
            messagebox.showerror("Camera Error", "Camera not accessible. Please check if it's connected, enabled, or in use by another application.")

    def stop_camera(self):
        if self.is_continuous_capture_active:
            messagebox.showwarning("Continuous Capture Active", "Please stop Continuous Capture first.")
            return
        if self.is_timer_capture_active:
            messagebox.showwarning("Timer Capture Active", "Please stop Timer Capture first.")
            return
        
        if self.camera_running:
            self._stop_camera_stream()
            messagebox.showinfo("Camera Status", "Camera stopped.")
        else:
            messagebox.showinfo("Camera Status", "Camera is already off.")

    def auto_capture_photo(self):
        if not self.cap or not self.cap.isOpened():
            if not self.is_continuous_capture_active and not self.is_timer_capture_active:
                self.master.after(0, messagebox.showwarning, "Capture Error", "Camera is not open or accessible to capture an image from.")
            self._log_event("Auto-capture failed: Camera stream not active.")
            return None

        ret, frame = self.cap.read()
        if not ret:
            if not self.is_continuous_capture_active and not self.is_timer_capture_active:
                self.master.after(0, messagebox.showwarning, "Capture Error", "Failed to read frame from camera for capture.")
            self._log_event("Auto-capture failed: Failed to read frame from camera.")
            return None

        self.last_live_camera_frame = frame

        path = os.path.join(single_image_folder, self.get_unique_image_name(f"auto_live_camera"))

        current_jpeg_quality = jpeg_quality
        if self.is_continuous_capture_active or self.is_timer_capture_active:
            current_jpeg_quality = random.randint(30, 80)
            self._log_event(f"Automated Capture: Using JPEG Quality = {current_jpeg_quality}")

        try:
            cv2.imwrite(path, frame, [int(cv2.IMWRITE_JPEG_QUALITY), current_jpeg_quality])
            self.last_captured_filename = path
            if not self.is_timer_capture_active:
                self.master.after(0, self._display_image_in_label, self.captured_img_label, frame, (DISPLAY_AREA_WIDTH, DISPLAY_AREA_HEIGHT))
            
            self._log_event(f"Photo captured with Q={current_jpeg_quality}: {os.path.basename(path)}")
            
            return path
        except Exception as e:
            self.master.after(0, messagebox.showerror, "Save Error", f"Failed to save captured image: {e}")
            self._log_event(f"ERROR: Failed to save captured image {os.path.basename(path)}: {e}")
            return None

    def send_stored_image(self):
        if self.is_timer_capture_active:
            self.master.after(0, self._log_event, "Manual send blocked: Timer capture is active.")
            return
        if self.is_continuous_capture_active:
            self.master.after(0, self._log_event, "Manual send blocked: Continuous Capture is active.")
            return

        if self.last_captured_filename and os.path.exists(self.last_captured_filename):
            self._log_event(f"Manually attempting to send: {os.path.basename(self.last_captured_filename)} (Pop-ups suppressed).")
            self.send_data_to_receiver_threaded(self.last_captured_filename, silent_mode=True)
        else:
            self.master.after(0, self._log_event, "Manual send failed: No image is currently stored for transmission. Please 'Capture Single' or 'Choose Image' first.")
            # Removed: Update label when no image is available for manual send
            # self.master.after(0, self.transmission_progress_label.config, {"text": "Transmission Status: No Image", "bootstyle": "dark"})


    def _send_queued_images_task(self):
        while not self.captured_image_queue.empty():
            img_path_to_send = self.captured_image_queue.get()
            self._log_event(f"Attempting to send image from queue: {os.path.basename(img_path_to_send)}")
            self.send_data_to_receiver_threaded(img_path_to_send, silent_mode=True)

    def choose_image_for_display(self):
        filepaths = filedialog.askopenfilenames(
            title="Select Image File(s) to Display",
            filetypes=[("Image files", ".jpg;.png;.jpeg"), ("All files", ".*")]
        )
        if not filepaths:
            self._log_event("Choose image cancelled by user.")
            return

        selected_path = filepaths[0]
        img = cv2.imread(selected_path)
        if img is not None:
            filename = self.get_unique_image_name("chosen")
            save_path = os.path.join(single_image_folder, filename)
            try:
                cv2.imwrite(save_path, img, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
                self.last_captured_filename = save_path
                self.master.after(0, self._display_image_in_label, self.captured_img_label, img, (DISPLAY_AREA_WIDTH, DISPLAY_AREA_HEIGHT))
                self._log_event(f"Chose and stored image: {os.path.basename(save_path)}")
            except Exception as e:
                self.master.after(0, messagebox.showerror, "File Save Error", f"Could not save selected image {os.path.basename(selected_path)}: {e}")
                self._log_event(f"ERROR: Could not save chosen image {os.path.basename(selected_path)}: {e}")
        else:
            self.master.after(0, messagebox.showwarning, "Invalid Image", f"Could not read image file: {os.path.basename(selected_path)}")
            self._log_event(f"ERROR: Could not read image file: {os.path.basename(selected_path)}")

    # --- Timer Capture Functions (including sleep cycle) (Unchanged) ---
    def toggle_timer_capture(self):
        if self.is_timer_capture_active:
            self.is_timer_capture_active = False
            self.timer_start_time = None
            self.timer_cycle_end_time = None
            self.timer_next_active_time = None

            if self.timer_capture_thread and self.timer_capture_thread.is_alive():
                self.timer_capture_thread.join(timeout=1)
                if self.timer_capture_thread.is_alive():
                    self._log_event("Warning: Timer capture thread did not terminate promptly.")
            
            self.timer_capture_button.config(text="▶ Start Timer Capture", bootstyle="success-outline")
            self._update_timer_status_label(None, "inactive")
            self._log_event("Timer Capture Stopped.")
            self.timer_count = 0
            
            self._resume_camera_display()

        else:
            if not self.camera_running:
                messagebox.showwarning("Camera Required", "Please start the live camera before starting Timer Capture.")
                self._log_event("Timer capture cannot start: Camera is off.")
                return

            if self.is_continuous_capture_active:
                messagebox.showwarning("Conflict", "Continuous Capture is active. Please stop it before starting Timer Capture.")
                self._log_event("Timer capture cannot start: Continuous Capture active.")
                return
            
            # MODIFIED: Validation for new byte size range
            if self.data_size_var.get() < 55 or self.data_size_var.get() > 100:
                messagebox.showwarning("Invalid Data Size", "The 'Data Size' must be between 55 and 100 bytes for Timer Capture to work.")
                self._log_event(f"Timer capture cannot start: Data Size ({self.data_size_var.get()}) is outside valid range (55-100).")
                return

            self.is_timer_capture_active = True
            self.timer_count = 0
            self.timer_start_time = time.time()
            self.timer_cycle_end_time = time.time() + self.timer_cycle_active_duration_seconds

            self._update_timer_status_label(None, "active")

            self.timer_capture_thread = threading.Thread(target=self._timer_capture_loop, daemon=True)
            self.timer_capture_thread.start()
            self.timer_capture_button.config(text="⏹ Stop Timer Capture", bootstyle="danger-outline")
            self._log_event(f"Timer Capture Started (Interval: {self.timer_capture_interval_ms /1000}s, Cycle: {self.timer_cycle_active_duration_seconds/60}m Active / {self.timer_cycle_sleep_duration_seconds/60}m Sleep).")

            self.master.after(1000, self._update_timer_overall_status)

    def _timer_capture_loop(self):
        self._log_event("Timer capture cycle loop started.")
        
        while self.is_timer_capture_active:
            self._log_event(f"Timer loop: Current state - is_timer_capture_active={self.is_timer_capture_active}")
            current_time = time.time()

            if self.timer_cycle_end_time and current_time < self.timer_cycle_end_time:
                self._log_event(f"Timer loop: In Active Phase. Time left: {int(self.timer_cycle_end_time - current_time)}s")
                
                captured_path = self.auto_capture_photo()
                if captured_path:
                    self.send_data_to_receiver_threaded(captured_path, silent_mode=True)
                
                sleep_chunk = 0.1
                time_slept = 0
                while time_slept < (self.timer_capture_interval_ms / 1000.0) and self.is_timer_capture_active and time.time() < self.timer_cycle_end_time:
                    time.sleep(sleep_chunk)
                    time_slept += sleep_chunk
                
                if not self.is_timer_capture_active:
                    self._log_event("Timer loop: Active phase exited due to stop signal.")
                    break
                if time.time() >= self.timer_cycle_end_time:
                    self._log_event("Timer loop: Active phase time completed. Transitioning to sleep.")

            elif self.is_timer_capture_active:
                self._log_event("Timer cycle: Active phase ended. Entering sleep phase.")
                self._pause_camera_display()
                self.timer_next_active_time = time.time() + self.timer_cycle_sleep_duration_seconds
                self._update_timer_status_label(None, "sleeping")

                self._log_event(f"Timer loop: In Sleep Phase. Next active at: {datetime.datetime.fromtimestamp(self.timer_next_active_time).strftime('%H:%M:%S')}")
                while self.is_timer_capture_active and time.time() < self.timer_next_active_time:
                    remaining_sleep = int(self.timer_next_active_time - time.time())
                    self.master.after(0, self._update_timer_status_label, remaining_sleep, "sleeping")
                    time.sleep(1)

                if self.is_timer_capture_active:
                    self._log_event("Timer cycle: Sleep phase ended. Resuming active phase.")
                    self.timer_cycle_end_time = time.time() + self.timer_cycle_active_duration_seconds
                    self._resume_camera_display()
                    self._update_timer_status_label(None, "active")
                else:
                    self._log_event("Timer loop: Sleep phase exited due to stop signal.")
                    break

        self._log_event("Timer capture cycle loop ended.")

    def _update_timer_overall_status(self):
        if self.is_timer_capture_active and self.timer_start_time is not None:
            elapsed_seconds_overall = int(time.time() - self.timer_start_time)
            elapsed_minutes_overall = elapsed_seconds_overall // 60
            elapsed_seconds_remainder_overall = elapsed_seconds_overall % 60
            
            current_time = time.time()
            if self.timer_cycle_end_time and current_time < self.timer_cycle_end_time:
                remaining_phase_seconds = int(self.timer_cycle_end_time - current_time)
                phase_type = "Active"
                bootstyle = "success"
            elif self.timer_next_active_time and current_time < self.timer_next_active_time:
                remaining_phase_seconds = int(self.timer_next_active_time - current_time)
                phase_type = "Sleeping"
                bootstyle = "warning"
            else:
                remaining_phase_seconds = 0
                phase_type = "Transitioning"
                bootstyle = "info"

            remaining_phase_minutes = remaining_phase_seconds // 60
            remaining_phase_seconds_remainder = remaining_phase_seconds % 60

            status_text = (
                f"Timer Capture: {phase_type}\n"
                f"Time in current phase: {remaining_phase_minutes:02d}m {remaining_phase_seconds_remainder:02d}s left\n"
                f"Images Sent: {self.timer_count}\n" # This still uses timer_count for timer mode
                f"Total Time: {elapsed_minutes_overall:02d}m {elapsed_seconds_remainder_overall:02d}s"
            )
            self.master.after(0, self.timer_capture_status_label.config, {"text": status_text, "bootstyle": bootstyle})
            
            self.master.after(1000, self._update_timer_overall_status)
        else:
            self._update_timer_status_label(None, "inactive")

    def _update_timer_status_label(self, remaining_seconds=None, status_type="inactive"):
        status_text = ""
        bootstyle = "dark"
        if status_type == "inactive":
            status_text = "Timer Capture: Inactive"
        elif status_type == "active":
            status_text = "Timer Capture: Active (Capturing & Sending)"
            bootstyle = "success"
        elif status_type == "sleeping":
            if remaining_seconds is not None:
                mins = remaining_seconds // 60
                secs = remaining_seconds % 60
                status_text = f"Timer Capture: Sleeping for {mins:02d}m {secs:02d}s"
            else:
                status_text = "Timer Capture: Sleeping"
            bootstyle = "warning"
        
        self.master.after(0, self.timer_capture_status_label.config, {"text": status_text, "bootstyle": bootstyle})

    # --- GUI Creation Methods (Modified for Dashboard Layout) ---

    def _create_widgets(self):
        self.master.configure(bg="#f0f0f0")  # Lighter background
        # Configure grid for main window: 1 row for header, 1 for main content, 1 for footer
        self.master.grid_rowconfigure(0, weight=0) # Top bar (header)
        self.master.grid_rowconfigure(1, weight=1) # Main content area (stretches)
        self.master.grid_rowconfigure(2, weight=0) # Bottom bar (footer)
        self.master.grid_columnconfigure(0, weight=0, minsize=self.SIDEBAR_WIDTH) # Sidebar (fixed width)
        self.master.grid_columnconfigure(1, weight=1) # Main content area (stretches)

        self._create_top_bar()
        self._create_sidebar()
        self._create_main_content_area()
        self._create_bottom_bar() # Re-added for the send/choose buttons

    def _create_top_bar(self):
        top_frame = tb.Frame(self.master, bootstyle="primary", relief=self.RELIEF_STYLE, borderwidth=self.BORDER_WIDTH)
        top_frame.grid(row=0, column=0, columnspan=2, sticky="ew") # Spans both sidebar and main content columns
        top_frame.grid_columnconfigure(0, weight=1)

        self.transmittal_label = tb.Label(top_frame, text=f"📡 {TRANSMITTER_NAME} Image Transmission Dashboard",
                                             font=("Segoe UI", 20, "bold"), bootstyle="inverse-primary", anchor="w")
        self.transmittal_label.pack(padx=20, pady=10, fill="x")

    def _create_sidebar(self):
        sidebar_frame = tb.Frame(self.master, bootstyle="light", relief="flat", borderwidth=0) # Changed to light
        sidebar_frame.grid(row=1, column=0, sticky="nswe", padx=(self.PADDING_X, 0), pady=(0, self.PADDING_Y)) # Occupies row 1, col 0
        sidebar_frame.grid_rowconfigure(99, weight=1) # Push content to top

        sidebar_buttons_cfg = {"bootstyle": "primary-outline", "width": 25, "padding": 12, "cursor": "hand2"} # Adjusted bootstyle

        # Buttons with slight margin from top of sidebar
        tb.Label(sidebar_frame, text="Navigation", font=("Segoe UI", 14, "bold"), bootstyle="inverse-light").pack(pady=(20, 10)) # Adjusted bootstyle

        tb.Button(sidebar_frame, text="📂 Files Folder", command=self.show_files_folder, **sidebar_buttons_cfg).pack(pady=5, padx=self.SIDEBAR_BUTTON_PAD_X, fill="x")
        tb.Button(sidebar_frame, text="🖼 Images Folder", command=self.show_images_folder, **sidebar_buttons_cfg).pack(pady=5, padx=self.SIDEBAR_BUTTON_PAD_X, fill="x")
        tb.Button(sidebar_frame, text="📦 Frames Folder", command=self.show_frames_folder, **sidebar_buttons_cfg).pack(pady=5, padx=self.SIDEBAR_BUTTON_PAD_X, fill="x")
        tb.Button(sidebar_frame, text="⚙ Settings & About", command=self.show_settings_view, **sidebar_buttons_cfg).pack(pady=5, padx=self.SIDEBAR_BUTTON_PAD_X, fill="x")

        # Exit button positioned at the bottom, using grid to push it down
        exit_frame = tb.Frame(sidebar_frame, bootstyle="light") # Adjusted bootstyle
        exit_frame.pack(side="bottom", fill="x", pady=(20, 20), padx=self.SIDEBAR_BUTTON_PAD_X)
        tb.Button(exit_frame, text="🚪 Exit Application", command=self.exit_application, bootstyle="danger-outline", width=25, padding=12, cursor="hand2").pack(fill="x")


    def _create_main_content_area(self):
        main_content_frame = tb.Frame(self.master, bootstyle="secondary") # Main dashboard area
        main_content_frame.grid(row=1, column=1, sticky="nswe", padx=(0, self.PADDING_X), pady=(0, self.PADDING_Y))
        
        # Configure columns and rows for the main content dashboard
        main_content_frame.grid_columnconfigure(0, weight=1) # Left half of content area
        main_content_frame.grid_columnconfigure(1, weight=1) # Right half of content area
        main_content_frame.grid_rowconfigure(0, weight=1) # Top row: Camera/Stored Displays
        main_content_frame.grid_rowconfigure(1, weight=0) # Middle row: Control Buttons
        main_content_frame.grid_rowconfigure(2, weight=0) # Bottom row: Status Labels

        # --- Top Row: Live Camera and Stored Image Display ---
        # Live Camera Feed Panel (Left side of main content)
        live_camera_box = tb.LabelFrame(main_content_frame, text="📸 Live Camera Feed", bootstyle="primary") # Changed to primary
        live_camera_box.grid(row=0, column=0, sticky="nswe", padx=self.PADDING_X, pady=self.PADDING_Y)
        live_camera_box.grid_propagate(False)
        live_camera_box.grid_columnconfigure(0, weight=1)
        live_camera_box.grid_rowconfigure(0, weight=1)
        self.live_camera_feed_label = tb.Label(live_camera_box, text="📸 Live Camera Feed\n(Camera Off)",
                                                 background="#e9ecef", foreground="#495057", anchor="center", font=("Segoe UI", 12)) # Light background, dark text
        self.live_camera_feed_label.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # Captured Image Display Area (Right side of main content)
        captured_img_box = tb.LabelFrame(main_content_frame, text="📸 Stored Image Display", bootstyle="primary") # Changed to primary
        captured_img_box.grid(row=0, column=1, sticky="nswe", padx=(0, self.PADDING_X), pady=self.PADDING_Y)
        captured_img_box.grid_propagate(False)
        captured_img_box.grid_columnconfigure(0, weight=1)
        captured_img_box.grid_rowconfigure(0, weight=1)
        self.captured_img_label = tb.Label(captured_img_box, text="📸 Stored Image Display",
                                                 background="#e9ecef", foreground="#495057", anchor="center", font=("Segoe UI", 12)) # Light background, dark text
        self.captured_img_label.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # --- Middle Row: Camera and Capture Controls ---
        controls_frame = tb.Frame(main_content_frame, bootstyle="secondary")
        controls_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=self.PADDING_X, pady=(self.PADDING_Y, 0))
        controls_frame.grid_columnconfigure(0, weight=1)
        controls_frame.grid_columnconfigure(1, weight=1)
        controls_frame.grid_columnconfigure(2, weight=1)
        controls_frame.grid_columnconfigure(3, weight=1)
        controls_frame.grid_columnconfigure(4, weight=1) # For byte rate control

        btn_cfg_wide = {"width": 25, "padding": 10, "cursor": "hand2"}

        # Camera Control Buttons
        tb.Button(controls_frame, text="▶ Start Live Camera", command=self.start_camera, bootstyle="primary", **btn_cfg_wide).grid(row=0, column=0, padx=5, pady=self.WIDGET_PAD_Y)
        tb.Button(controls_frame, text="⏹ Stop Live Camera", command=self.stop_camera, bootstyle="primary", **btn_cfg_wide).grid(row=0, column=1, padx=5, pady=self.WIDGET_PAD_Y)
        tb.Button(controls_frame, text="📸 Capture Single", command=self.auto_capture_photo, bootstyle="success", **btn_cfg_wide).grid(row=0, column=2, padx=5, pady=self.WIDGET_PAD_Y)
        
        # Data Size/Byte Rate Adjust integrated here for easy access
        byte_rate_frame = tb.Frame(controls_frame, bootstyle="secondary") # Using main_content_frame's bootstyle
        byte_rate_frame.grid(row=0, column=3, columnspan=2, sticky="ew", padx=5, pady=self.WIDGET_PAD_Y)
        byte_rate_frame.grid_columnconfigure(0, weight=0)
        byte_rate_frame.grid_columnconfigure(1, weight=1)
        byte_rate_frame.grid_columnconfigure(2, weight=0)

        tb.Label(byte_rate_frame, text=f"Total Frame Size (incl. {header_size}B header):", font=("Segoe UI", 10), bootstyle="inverse-secondary").grid(row=0, column=0, padx=5, sticky="w")
        # MODIFIED: Changed 'from_' and 'to' range for byte_rate_scale
        self.byte_rate_scale = tb.Scale(byte_rate_frame, from_=55, to=100, orient="horizontal",
                                             variable=self.data_size_var, command=self.update_data_size_display, bootstyle="info")
        self.byte_rate_scale.grid(row=0, column=1, sticky="ew", padx=5)
        self.byte_rate_label = tb.Label(byte_rate_frame, text=f"{self.data_size_var.get()} bytes", font=("Segoe UI", 10, "bold"), bootstyle="inverse-secondary")
        self.byte_rate_label.grid(row=0, column=2, padx=5, sticky="w")
        self.data_size_var.trace_add("write", self.update_data_size_display)


        # --- Bottom Row: Continuous and Timer Capture Controls/Status ---
        capture_modes_frame = tb.Frame(main_content_frame, bootstyle="secondary")
        capture_modes_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=self.PADDING_X, pady=(0, self.PADDING_Y))
        capture_modes_frame.grid_columnconfigure(0, weight=1) # For continuous capture
        capture_modes_frame.grid_columnconfigure(1, weight=1) # For timer capture
        # Removed: capture_modes_frame.grid_columnconfigure(2, weight=1) # For transmission progress (no longer needed)

        # Continuous Capture
        continuous_capture_group = tb.LabelFrame(capture_modes_frame, text="Continuous Capture", bootstyle="info") # Changed to info
        continuous_capture_group.grid(row=0, column=0, sticky="nswe", padx=10, pady=5)
        continuous_capture_group.grid_columnconfigure(0, weight=1)
        self.continuous_capture_button = tb.Button(continuous_capture_group, text="▶ Start Continuous Capture",
                                                     command=self.toggle_continuous_capture,
                                                     bootstyle="success-outline", width=30, padding=10)
        self.continuous_capture_button.pack(pady=(10, 5), padx=10, fill="x")
        self.continuous_capture_status_label = tb.Label(continuous_capture_group, text="Continuous Capture: Inactive",
                                                          bootstyle="info", anchor="center")
        self.continuous_capture_status_label.pack(pady=(0, 10), padx=10, fill="x")

        # Timer Capture
        timer_capture_group = tb.LabelFrame(capture_modes_frame, text="Timer Capture", bootstyle="info") # Changed to info
        timer_capture_group.grid(row=0, column=1, sticky="nswe", padx=10, pady=5)
        timer_capture_group.grid_columnconfigure(0, weight=1)
        self.timer_capture_button = tb.Button(timer_capture_group, text="▶ Start Timer Capture",
                                                command=self.toggle_timer_capture,
                                                bootstyle="secondary-outline", width=30, padding=10)
        self.timer_capture_button.pack(pady=(10, 5), padx=10, fill="x")
        self.timer_capture_status_label = tb.Label(timer_capture_group, text="Timer Capture: Inactive",
                                                      bootstyle="info", anchor="center", wraplength=250)
        self.timer_capture_status_label.pack(pady=(0, 10), padx=10, fill="x")

        # Removed: Transmission Progress Label (was here)
        # progress_group = tb.LabelFrame(capture_modes_frame, text="Transmission Status", bootstyle="info")
        # progress_group.grid(row=0, column=2, sticky="nswe", padx=10, pady=5)
        # progress_group.grid_columnconfigure(0, weight=1)
        # self.transmission_progress_label = tb.Label(progress_group, text="Transmission Status: Idle",
        #                                              font=("Segoe UI", 16, "bold"), bootstyle="info", anchor="center", wraplength=300)
        # self.transmission_progress_label.pack(expand=True, fill="both", padx=10, pady=10)


    def _create_bottom_bar(self):
        bottom_frame = tb.Frame(self.master, bootstyle="primary", relief=self.RELIEF_STYLE, borderwidth=self.BORDER_WIDTH)
        bottom_frame.grid(row=2, column=0, columnspan=2, sticky="ew") # Spans both sidebar and main content columns
        bottom_frame.grid_columnconfigure(0, weight=1)
        bottom_frame.grid_columnconfigure(1, weight=1)

        choose_img_btn = tb.Button(bottom_frame, text="🗂 Choose Image for Display", bootstyle="info-outline",
                                     width=35, padding=12, command=self.choose_image_for_display, cursor="hand2")
        choose_img_btn.grid(row=0, column=0, padx=20, pady=10, sticky="e")

        send_stored_btn = tb.Button(bottom_frame, text="🚀 Send Stored Image", bootstyle="success",
                                     width=35, padding=15,
                                     command=self.send_stored_image, cursor="hand2")
        send_stored_btn.grid(row=0, column=1, padx=20, pady=10, sticky="w")


    # --- Shared Image Display Helper (Unchanged) ---
    def _display_image_in_label(self, label_widget, cv2_frame, target_size=None):
        if cv2_frame is None or cv2_frame.shape[0] == 0 or cv2_frame.shape[1] == 0:
            label_widget.config(image='')
            return

        cv2image = cv2.cvtColor(cv2_frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(cv2image)

        if target_size:
            width, height = target_size
        else:
            width = label_widget.winfo_width()
            height = label_widget.winfo_height()
            if width <= 0 or height <= 0:
                width, height = DISPLAY_AREA_WIDTH, DISPLAY_AREA_HEIGHT

        img.thumbnail((width, height), Image.Resampling.LANCZOS)
        imgtk = ImageTk.PhotoImage(image=img)
        label_widget.config(image=imgtk, text="", bootstyle="inverse-primary") # Adjusted bootstyle
        label_widget.image = imgtk

    # --- UI Update Callbacks (Modified for new byte range validation) ---
    def update_data_size_display(self, *args):
        current_data_size = self.data_size_var.get()
        self.byte_rate_label.config(text=f"{current_data_size} bytes (Image data: {current_data_size - header_size} bytes)")
        # MODIFIED: New condition for valid range (55-100)
        if current_data_size < 55 or current_data_size > 100: 
            self.byte_rate_label.config(bootstyle="danger")
            self._log_event(f"WARNING: Data Size ({current_data_size} bytes) is outside the valid range (55-100 bytes). Please adjust.")
        else:
            self.byte_rate_label.config(bootstyle="inverse-secondary")


    def _log_event(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_message = f"[{timestamp}] {message}"
        print(log_message) # Print to console/terminal

    def toggle_continuous_capture(self):
        if self.is_continuous_capture_active:
            self.is_continuous_capture_active = False
            
            if self.continuous_capture_thread and self.continuous_capture_thread.is_alive():
                self.continuous_capture_thread.join(timeout=1)
            if self.continuous_capture_thread and self.continuous_capture_thread.is_alive():
                self._log_event("Warning: Continuous capture thread did not terminate promptly.")
            
            self.continuous_capture_button.config(text="▶ Start Continuous Capture", bootstyle="success-outline")
            self.continuous_capture_status_label.config(text="Continuous Capture: Inactive", bootstyle="dark")
            self._log_event("Continuous Capture Stopped.")
        else:
            if not self.camera_running:
                messagebox.showwarning("Camera Required", "Please start the live camera before starting Continuous Capture.")
                self._log_event("Continuous capture cannot start: Camera is off.")
                return
            
            if self.is_timer_capture_active:
                messagebox.showwarning("Conflict", "Timer Capture is active. Please stop it before starting Continuous Capture.")
                self._log_event("Continuous capture cannot start: Timer Capture active.")
                return

            # MODIFIED: Validation for new byte size range
            if self.data_size_var.get() < 55 or self.data_size_var.get() > 100:
                messagebox.showwarning("Invalid Data Size", "The 'Data Size' must be between 55 and 100 bytes for Continuous Capture to work.")
                self._log_event(f"Continuous capture cannot start: Data Size ({self.data_size_var.get()}) is outside valid range (55-100).")
                return

            self.is_continuous_capture_active = True
            
            self.continuous_capture_thread = threading.Thread(target=self._continuous_capture_loop, daemon=True)
            self.continuous_capture_thread.start()
            self.continuous_capture_button.config(text="⏹ Stop Continuous Capture", bootstyle="danger-outline")
            self.continuous_capture_status_label.config(text="Continuous Capture: Active", bootstyle="success")
            self._log_event(f"Continuous Capture Started (Interval: {self.continuous_capture_interval_ms / 1000}s).")

    def _continuous_capture_loop(self):
        while self.is_continuous_capture_active:
            captured_path = self.auto_capture_photo()
            if captured_path:
                self.send_data_to_receiver_threaded(captured_path, silent_mode=True)
            time.sleep(self.continuous_capture_interval_ms / 1000.0)

    # --- Folder Handling and Exit (Unchanged) ---
    def show_files_folder(self):
        try:
            path = BASE_DIR
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            self._log_event(f"Opened base directory: {path}")
        except Exception as e:
            self._log_event(f"Error opening files folder: {e}")
            messagebox.showerror("Error", f"Could not open folder: {e}")

    def show_images_folder(self):
        try:
            path = single_image_folder
            os.makedirs(path, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            self._log_event(f"Opened single images folder: {path}")
        except Exception as e:
            self._log_event(f"Error opening images folder: {e}")
            messagebox.showerror("Error", f"Could not open folder: {e}")

    def show_frames_folder(self):
        try:
            path = frames_output_folder
            os.makedirs(path, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            self._log_event(f"Opened frames output folder: {path}")
        except Exception as e:
            self._log_event(f"Error opening frames folder: {e}")
            messagebox.showerror("Error", f"Could not open folder: {e}")

    def show_settings_view(self):
        messagebox.showinfo("Settings & About", "This is the settings and about section. Future configurations could go here.")
        self._log_event("Settings/About view requested.")

    def exit_application(self):
        if messagebox.askyesno("Exit Application", "Are you sure you want to exit? All active captures will stop."):
            self._log_event("Attempting to exit application...")
            self.is_continuous_capture_active = False
            self.is_timer_capture_active = False
            
            if self.continuous_capture_thread and self.continuous_capture_thread.is_alive():
                self.continuous_capture_thread.join(timeout=1)
            if self.timer_capture_thread and self.timer_capture_thread.is_alive():
                self.timer_capture_thread.join(timeout=1)

            if self.cap and self.cap.isOpened():
                self._stop_camera_stream()

            self.master.destroy()
            self._log_event("Application exited gracefully.")
            sys.exit(0)


if __name__ == "__main__":
    try:
        import numpy as np
    except ImportError:
        print("Numpy not found. Please install it: pip install numpy")
        sys.exit(1)

    app_style = tb.Style('lumen') 
    root = app_style.master

    app_style.configure("GreenTitle.TLabelframe.Label", foreground=app_style.colors.primary, font=("Segoe UI", 12))
    
    app = TransmitterApp(root)
    root.mainloop()