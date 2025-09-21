import tkinter as tk
from tkinter import messagebox, filedialog
import ttkbootstrap as tb
from ttkbootstrap.constants import *
import cv2
from PIL import Image, ImageTk
import threading
import datetime
import os
import socket
import sys
import subprocess
import struct
import numpy as np
import time

# --- Global/Configuration Variables ---
RECEIVER_NAME = "RX"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define the new single base folder for all receiver output
receiver_output_base_folder = os.path.join(BASE_DIR, f"{RECEIVER_NAME}_Output")

HOST = '0.0.0.0'
PORT = 49697 # Ensure this port matches your sender's configuration
SERVER_LISTEN_BACKLOG = 5

# Ensure the top-level output folder exists
os.makedirs(receiver_output_base_folder, exist_ok=True)

class ReceiverApp:
    def __init__(self, master):
        self.master = master
        master.title(f"🖥️ {RECEIVER_NAME} Image Receiver Dashboard")
        master.state('zoomed')
        master.protocol("WM_DELETE_WINDOW", self.exit_application)

        # --- UI Layout Configuration Constants ---
        self.PADDING_X = 15
        self.PADDING_Y = 15
        self.BORDER_WIDTH = 2
        self.RELIEF_STYLE = "flat"
        self.WIDGET_PAD_Y = 10
        self.SIDEBAR_BUTTON_PAD_X = 15
        # Adjusted display area for smaller live feeds
        self.DISPLAY_AREA_WIDTH = 320
        self.DISPLAY_AREA_HEIGHT = 240
        self.THUMBNAIL_SIZE = (120, 90) # Size for thumbnails in 'All Images Displayed'
        self.SCROLLBAR_PAD = 5 # New constant for scrollbar padding

        # --- Application State Variables ---
        self.server_socket = None
        self.server_running = False
        self.server_thread = None
        self.active_connections = []

        self.received_image_count = 0
        self.total_frames_received_for_current_image = 0
        # Store dicts: {'path': '...', 'transmitter': '...', 'timestamp': '...'}
        self.all_received_images_metadata = []
        
        # Define the new list to dynamically manage live feed assignments
        # Each entry will be a dictionary: {'label_widget': self.live_feed_labels[i], 'transmitter_name': 'TX_NAME', 'last_image_data': cv2_image}
        self.live_feed_assignments = [
            {'label_widget': None, 'transmitter_name': 'N/A', 'last_image_data': None, 'label_frame_widget': None},
            {'label_widget': None, 'transmitter_name': 'N/A', 'last_image_data': None, 'label_frame_widget': None},
            {'label_widget': None, 'transmitter_name': 'N/A', 'last_image_data': None, 'label_frame_widget': None},
            {'label_widget': None, 'transmitter_name': 'N/A', 'last_image_data': None, 'label_frame_widget': None}
        ]

        # --- GUI Elements References ---
        self.server_status_label = None
        self.event_log_text = None
        self.last_received_img_label = None # Will be repurposed if needed, but the image shows 4 display areas
        self.received_info_label = None
        self.all_images_display_frame = None # This will be removed or repurposed
        self.all_images_canvas = None
        self.all_images_scrollbar = None
        self.all_images_inner_frame = None # Frame inside canvas to hold image labels
        self.tx_select_combobox = None

        # New references for the four live feed displays
        self.live_feed_labels = []
        # Store the last received image data (cv2 format) for each live feed display
        # This is crucial for the "double click to open new screen" feature.
        # self.live_feed_current_images = [None, None, None, None] # This will be managed by live_feed_assignments

        # Initialize GUI components
        self._create_widgets()
        self._log_event("Receiver application started.")

    # --- Backend/Core Functionality ---

    def start_server(self):
        if self.server_running:
            self._log_event("Server already running request received.")
            return

        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((HOST, PORT))
            self.server_socket.listen(SERVER_LISTEN_BACKLOG)
            self.server_running = True
            self._update_server_status_display()
            self._log_event(f"Server started, listening on {HOST}:{PORT}")

            self.server_thread = threading.Thread(target=self._accept_connections_task, daemon=True)
            self.server_thread.start()

        except OSError as e:
            self.master.after(0, lambda: messagebox.showerror("Server Error", f"Could not start server: {e}\nIs the port in use or are permissions missing?"))
            self._log_event(f"❌ Server start failed: {e}")
            self.server_running = False
            self._update_server_status_display()
        except Exception as e:
            self.master.after(0, lambda: messagebox.showerror("Server Error", f"An unexpected error occurred while starting server: {e}"))
            self._log_event(f"❌ Unexpected server error: {e}")
            self.server_running = False
            self._update_server_status_display()

    def _accept_connections_task(self):
        while self.server_running:
            try:
                self.server_socket.settimeout(1.0)
                conn, addr = self.server_socket.accept()
                self._log_event(f"Connection established with {addr[0]}:{addr[1]}")
                client_handler_thread = threading.Thread(target=self._handle_client_connection, args=(conn, addr), daemon=True)
                client_handler_thread.start()
                self.active_connections.append(client_handler_thread)
            except socket.timeout:
                continue
            except socket.error as e:
                if self.server_running:
                    self._log_event(f"❌ Server accept error: {e}")
                break
            except Exception as e:
                self._log_event(f"❌ Error accepting connection: {e}")
                if not self.server_running:
                    break

    def _handle_client_connection(self, conn, addr):
        transmitter_addr = f"{addr[0]}:{addr[1]}"
        self._log_event(f"Handling data from {transmitter_addr}...")
        conn.settimeout(60.0)

        try:
            transmitter_name_bytes = self._recv_all(conn, 50)
            if not transmitter_name_bytes: raise ConnectionAbortedError("Failed to receive transmitter name.")
            transmitter_name = transmitter_name_bytes.decode('utf-8').strip('\x00')
            self._log_event(f"Received transmitter name: {transmitter_name}")
            self.current_transmitter_name = transmitter_name

            # --- Define and create transmitter-specific folders within the new consolidated structure ---
            tx_main_folder = os.path.join(receiver_output_base_folder, transmitter_name)
            os.makedirs(tx_main_folder, exist_ok=True)
            self._log_event(f"Main output folder for {transmitter_name}: {tx_main_folder}")

            # Image save folder for this transmitter
            transmitter_specific_images_folder = os.path.join(tx_main_folder, 'images')
            os.makedirs(transmitter_specific_images_folder, exist_ok=True)
            self._log_event(f"Images for {transmitter_name} will be saved to: {transmitter_specific_images_folder}")

            # Raw frames base folder for this transmitter
            transmitter_specific_frames_base_folder = os.path.join(tx_main_folder, 'frames')
            os.makedirs(transmitter_specific_frames_base_folder, exist_ok=True)
            self._log_event(f"Raw frames for {transmitter_name} will be saved to: {transmitter_specific_frames_base_folder}")
            # --- End transmitter-specific folder creation ---

            filename_bytes = self._recv_all(conn, 100)
            if not filename_bytes: raise ConnectionAbortedError("Failed to receive filename.")
            filename = filename_bytes.decode('utf-8').strip('\x00')
            self._log_event(f"Received filename: {filename}")

            data_size_bytes = self._recv_all(conn, 4)
            if not data_size_bytes: raise ConnectionAbortedError("Failed to receive data size.")
            # data_size is now the total size of (header + chunk) as per user's description
            data_size = int.from_bytes(data_size_bytes, 'big') 
            if data_size <= 0: raise ValueError(f"Invalid data size received: {data_size}")
            self._log_event(f"Received data size (including header): {data_size} bytes")

            # --- MODIFIED: Use a dictionary to store chunks by (row, col) tuple for correct spatial reconstruction ---
            frame_grid = {} # Stores { (row_idx, col_idx): chunk_data }
            max_row = -1
            max_col = -1
            # --- END MODIFIED ---

            frame_metadata = {} # This seems unused after changes, can be removed if not needed for other purposes
            expected_header_size = 10
            # MODIFIED: expected_frame_content_size is now just the data_size received
            expected_frame_content_size = data_size 
            total_frames_expected = -1

            self.total_frames_received_for_current_image = 0
            self.master.after(0, lambda: self._update_received_info_display(self.received_image_count, total_frames_expected, f"Receiving...", transmitter_name))

            # Create a unique subfolder for raw frames of the current image within the transmitter's frames folder
            timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            image_name_without_ext = os.path.splitext(filename)[0]
            current_raw_frames_dir = os.path.join(transmitter_specific_frames_base_folder, f"{image_name_without_ext}_{timestamp_str}")
            os.makedirs(current_raw_frames_dir, exist_ok=True)
            self._log_event(f"Saving individual frames to: {current_raw_frames_dir}")


            while True:
                # MODIFIED: Receiving the 'data_size' which is the combined header + chunk size
                full_frame_data = self._recv_all(conn, expected_frame_content_size)
                if not full_frame_data:
                    self._log_event("Client disconnected or end of stream.")
                    break

                # --- MODIFIED: Save the full_frame_data directly without separating header ---
                header = full_frame_data[:expected_header_size]
                chunk = full_frame_data[expected_header_size:] # Still extract chunk for reconstruction logic

                frame_idx = int.from_bytes(header[0:2], 'big') # This frame_idx is now less critical for order but useful for total count
                row_idx = int.from_bytes(header[2:4], 'big')
                col_idx = int.from_bytes(header[4:6], 'big')
                current_total_frames = int.from_bytes(header[6:8], 'big')

                if total_frames_expected == -1:
                    total_frames_expected = current_total_frames
                    self._log_event(f"Expecting {total_frames_expected} total frames for {filename}")
                elif total_frames_expected != current_total_frames:
                     self._log_event(f"WARN: Total frames mismatch. Expected {total_frames_expected}, got {current_total_frames} for frame (R:{row_idx}, C:{col_idx}). Continuing with first received total.")

                # Save individual raw frame, including row/col in filename for clarity
                # MODIFICATION START: Changed frame naming to match Transmitter.py
                frame_filepath = os.path.join(current_raw_frames_dir, f"frame_{frame_idx:04d}_{row_idx}_{col_idx}.bin")
                # MODIFICATION END
                try:
                    # Save the full_frame_data (header + chunk)
                    with open(frame_filepath, 'wb') as f:
                        f.write(full_frame_data) # Changed from 'chunk' to 'full_frame_data'
                    # self._log_event(f"Saved raw frame {frame_idx} to {frame_filepath}") # Too verbose, uncomment for deep debug
                except Exception as save_err:
                    self._log_event(f"ERROR: Could not save raw frame (R:{row_idx}, C:{col_idx}) to {frame_filepath}: {save_err}")

                # --- MODIFIED: Store chunk in the grid by (row_idx, col_idx) ---
                # Continue storing only the chunk for image reconstruction purposes
                frame_grid[(row_idx, col_idx)] = chunk
                max_row = max(max_row, row_idx)
                max_col = max(max_col, col_idx)

                self.total_frames_received_for_current_image = len(frame_grid) # Count unique (row, col) pairs
                self.master.after(0, lambda: self._update_received_info_display(self.received_image_count, total_frames_expected, f"Receiving frame {self.total_frames_received_for_current_image}/{total_frames_expected} (R:{row_idx}, C:{col_idx})...", transmitter_name))
                self._log_event(f"Received frame (R:{row_idx}, C:{col_idx}) from {transmitter_name}")
                # --- END MODIFIED ---
                
                if self.total_frames_received_for_current_image == total_frames_expected:
                    self._log_event(f"All {total_frames_expected} frames received for {filename}. Reconstructing...")
                    break

            if total_frames_expected > 0 and self.total_frames_received_for_current_image == total_frames_expected:
                # --- MODIFIED: Reconstruct the combined bytes in correct row-major order ---
                rows_to_combine = []
                # Iterate from 0 to max_row and 0 to max_col to ensure correct order
                for r in range(max_row + 1):
                    row_chunks = []
                    for c in range(max_col + 1):
                        if (r, c) in frame_grid:
                            row_chunks.append(frame_grid[(r, c)])
                        else:
                            # Handle missing chunk: log an error and insert empty bytes to avoid breaking the join
                            self._log_event(f"ERROR: Missing chunk at (Row:{r}, Col:{c}) during reconstruction for {filename}. Inserting empty bytes.")
                            row_chunks.append(b'') # Or a placeholder to indicate missing data
                    rows_to_combine.append(b''.join(row_chunks))
                
                combined_bytes = b''.join(rows_to_combine)
                # --- END MODIFIED ---

                # Save reconstructed image to the transmitter-specific images folder
                image_path = os.path.join(transmitter_specific_images_folder, filename)

                debug_filepath = None # Initialize to None

                try:
                    # IMPORTANT: cv2.imdecode expects a byte stream of a COMPRESSED image (e.g., JPEG, PNG).
                    # If your sender sends raw pixel data, it needs to be encoded (e.g., with cv2.imencode)
                    # on the sender side before transmission for this to work correctly.
                    nparr = cv2.imdecode(np.frombuffer(combined_bytes, np.uint8), cv2.IMREAD_COLOR)
                    
                    if nparr is None or nparr.size == 0:
                        # Add more specific error logging and save for debugging
                        debug_filepath = os.path.join(current_raw_frames_dir, f"FAILED_DECODE_{filename}_{timestamp_str}.bin")
                        with open(debug_filepath, 'wb') as f:
                            f.write(combined_bytes)
                        self._log_event(f"❌ WARNING: cv2.imdecode failed. Saved raw combined bytes to {debug_filepath} for inspection.")
                        raise ValueError("OpenCV could not decode the image data. This often means the sender did not send compressed image data (e.g., JPEG/PNG).")

                    cv2.imwrite(image_path, nparr)
                    self.last_received_image_path = image_path
                    self.received_image_count += 1
                    
                    # Store image metadata including transmitter name and timestamp
                    self.all_received_images_metadata.append({
                        'path': image_path,
                        'transmitter': transmitter_name,
                        'timestamp': datetime.datetime.now()
                    })

                    # MODIFIED: Assign received image to an appropriate live feed display
                    self._update_live_feed_display(transmitter_name, nparr)
                    
                    self.master.after(0, lambda: self._update_received_info_display(self.received_image_count, total_frames_expected, f"Image reconstructed successfully!", transmitter_name))
                    self._log_event(f"✅ Successfully received and saved: {filename}")
                    
                except Exception as img_err:
                    self.master.after(0, lambda: messagebox.showerror("Image Reconstruction Error", f"Failed to reconstruct image {filename}: {img_err}"))
                    self._log_event(f"❌ Image reconstruction failed for {filename}: {img_err}")
                    self._log_event(f"Raw frames for failed reconstruction are in: {current_raw_frames_dir}")
                    if debug_filepath: # Only log if it was created
                        self._log_event(f"Combined raw data for failed reconstruction is in: {debug_filepath}")
            else:
                self._log_event(f"Failed to receive all frames for {filename}. Expected {total_frames_expected}, got {self.total_frames_received_for_current_image}.")
                self._log_event(f"Partial raw frames are in: {current_raw_frames_dir}")


        except ConnectionAbortedError as e:
            self._log_event(f"Client {transmitter_addr} connection aborted: {e}")
        except socket.timeout:
            self._log_event(f"Client {transmitter_addr} timed out.")
        except socket.error as e:
            self.master.after(0, lambda: messagebox.showerror("Network Error", f"Socket error with client ({transmitter_name}): {e}"))
            self._log_event(f"❌ Socket error with {transmitter_addr}: {e}")
        except ValueError as e:
            self.master.after(0, lambda: messagebox.showerror("Data Error", f"Data format error from client ({transmitter_name}): {e}"))
            self._log_event(f"❌ Data format error from {transmitter_addr}: {e}")
        except Exception as e:
            self.master.after(0, lambda: messagebox.showerror("Reception Error", f"An unexpected error occurred while receiving from {transmitter_name}: {e}"))
            self._log_event(f"❌ Unexpected error from {transmitter_addr}: {e}")
        finally:
            if conn:
                conn.close()
                self._log_event(f"Connection with {transmitter_addr} closed.")
            if threading.current_thread() in self.active_connections:
                self.active_connections.remove(threading.current_thread())


    def _recv_all(self, sock, n):
        data = b''
        while len(data) < n:
            packet = sock.recv(n - len(data))
            if not packet:
                return None
            data += packet
        return data

    def stop_server(self):
        if not self.server_running:
            self._log_event("Server already off request received.")
            return

        self._log_event("Stopping server...")
        self.server_running = False
        try:
            if self.server_socket:
                self.server_socket.shutdown(socket.SHUT_RDWR)
                self.server_socket.close()
                self.server_socket = None
        except Exception as e:
            self._log_event(f"Error closing server socket: {e}")

        if self.server_thread and self.server_thread.is_alive():
            self._log_event("Waiting for server thread to terminate...")
            self.server_thread.join(timeout=2)
            if self.server_thread.is_alive():
                self._log_event("Server thread did not terminate gracefully.")

        for thread in list(self.active_connections):
            if thread.is_alive():
                self._log_event(f"Attempting to join client handler thread {thread.name}...")
                thread.join(timeout=1)
                if thread.is_alive():
                    self._log_event(f"Client handler thread {thread.name} did not terminate.")
        self.active_connections.clear()

        self._update_server_status_display()


    # --- GUI Creation Methods ---

    def _create_widgets(self):
        # Master grid configuration based on new image layout
        self.master.grid_columnconfigure(0, weight=1) # Main content area for video feeds
        self.master.grid_columnconfigure(1, weight=0, minsize=300) # Rightmost column for info and log
        self.master.grid_rowconfigure(0, weight=0) # Top bar
        self.master.grid_rowconfigure(1, weight=1) # Main content area

        self._create_top_bar()
        self._create_main_content_area() # Renamed and modified

    def _create_top_bar(self):
        top_frame = tb.Frame(self.master, bootstyle="light", relief=self.RELIEF_STYLE, borderwidth=self.BORDER_WIDTH)
        top_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(self.PADDING_Y, 0), padx=self.PADDING_X)
        
        # Grid for elements within the top_frame
        top_frame.grid_columnconfigure(0, weight=0) # Image / Open Folder / Status
        top_frame.grid_columnconfigure(1, weight=1) # Center section (Server Controls & New TX buttons)
        top_frame.grid_columnconfigure(2, weight=0) # Exit button
        top_frame.grid_rowconfigure(0, weight=1) # All elements on one row

        # --- Left section of top bar ---
        left_top_section = tb.Frame(top_frame)
        left_top_section.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        tb.Button(left_top_section, text="Image", command=self._image_button_action, bootstyle="secondary").pack(side="top", pady=2, fill="x")
        tb.Button(left_top_section, text="Open Folder", command=self.show_output_folder, bootstyle="secondary").pack(side="top", pady=2, fill="x")
        self.server_status_label = tb.Label(left_top_section, text="server status", anchor="center", font=("Segoe UI", 10, "bold"))
        self.server_status_label.pack(side="top", pady=2, fill="x")
        self._update_server_status_display() # Call here to set initial status

        # --- Middle section of top bar (Server Controls & New TX Buttons) ---
        middle_top_section = tb.Frame(top_frame)
        middle_top_section.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")
        middle_top_section.grid_columnconfigure(0, weight=1) # Start Server
        middle_top_section.grid_columnconfigure(1, weight=1) # Stop Server
        middle_top_section.grid_columnconfigure(2, weight=1) # TX1/TX3
        middle_top_section.grid_columnconfigure(3, weight=1) # TX2/TX4
        middle_top_section.grid_rowconfigure(0, weight=1) # Server buttons
        middle_top_section.grid_rowconfigure(1, weight=1) # TX buttons

        # Row 0: Server control buttons
        tb.Button(middle_top_section, text="Start Server", command=self.start_server, bootstyle="success").grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        tb.Button(middle_top_section, text="Stop Server", command=self.stop_server, bootstyle="danger").grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        
        # New: TX1 to TX4 buttons
        tb.Button(middle_top_section, text="TX1", command=lambda: self._open_transmitter_folder(transmitter_name="Tx1"), bootstyle="info").grid(row=0, column=2, padx=2, pady=2, sticky="ew")
        tb.Button(middle_top_section, text="TX2", command=lambda: self._open_transmitter_folder(transmitter_name="Tx2"), bootstyle="info").grid(row=0, column=3, padx=2, pady=2, sticky="ew")
        tb.Button(middle_top_section, text="TX3", command=lambda: self._open_transmitter_folder(transmitter_name="Tx3"), bootstyle="info").grid(row=1, column=2, padx=2, pady=2, sticky="ew")
        tb.Button(middle_top_section, text="TX4", command=lambda: self._open_transmitter_folder(transmitter_name="Tx4"), bootstyle="info").grid(row=1, column=3, padx=2, pady=2, sticky="ew")


        # Removed Byte size and Timer Set sliders and their frames

        # --- Right section of top bar ---
        right_top_section = tb.Frame(top_frame)
        right_top_section.grid(row=0, column=2, padx=5, pady=5, sticky="nsew")
        
        # MODIFIED: Use a custom bootstyle for the Exit button to apply font
        tb.Button(right_top_section, text="Exit", command=self.exit_application, 
                  bootstyle="BigDanger.TButton", # Apply the custom style
                  width=10 # Set a fixed width to make it visibly bigger
                 ).pack(side="right", pady=2, fill="x")

    # Placeholder functions for new buttons
    def _image_button_action(self):
        self._log_event("Image button clicked (placeholder).")

    # _auto_capture_action and _manual_capture_action are no longer bound to any buttons in the GUI.
    def _auto_capture_action(self):
        self._log_event("Auto capture action (no longer linked to a GUI button).")

    def _manual_capture_action(self):
        self._log_event("Manual capture action (no longer linked to a GUI button).")


    def _create_main_content_area(self):
        main_content_frame = tb.Frame(self.master)
        main_content_frame.grid(row=1, column=0, sticky="nswe", padx=(self.PADDING_X, 0), pady=(0, self.PADDING_Y))
        
        # Grid for the four "Live feed camera video display"
        main_content_frame.grid_columnconfigure(0, weight=1)
        main_content_frame.grid_columnconfigure(1, weight=1)
        main_content_frame.grid_rowconfigure(0, weight=1)
        main_content_frame.grid_rowconfigure(1, weight=1)

        # Create four live feed display areas
        self.live_feed_labels = [] # Clear any previous labels
        for r_idx in range(2):
            for c_idx in range(2):
                feed_index = r_idx * 2 + c_idx # 0, 1, 2, 3
                # Modified: LabelFrame text will be updated dynamically
                frame = tb.LabelFrame(main_content_frame, text=f"Live feed {feed_index + 1}: N/A", bootstyle="GreenTitle.TLabelframe")
                frame.grid(row=r_idx, column=c_idx, padx=self.PADDING_X // 2, pady=self.PADDING_Y // 2, sticky="nswe")
                frame.grid_propagate(False)
                frame.grid_columnconfigure(0, weight=1)
                frame.grid_rowconfigure(0, weight=1)

                label = tb.Label(frame, text=f"Waiting for feed...",
                                 foreground="gray", anchor="center", font=("Segoe UI", 12)) 
                label.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
                self.live_feed_labels.append(label)
                
                # Assign label widget to live_feed_assignments list
                self.live_feed_assignments[feed_index]['label_widget'] = label
                self.live_feed_assignments[feed_index]['label_frame_widget'] = frame # Store frame to update its text

                # Bind double-click event to open detailed view
                label.bind("<Double-Button-1>", lambda e, idx=feed_index: self._open_live_feed_detail_screen(idx))
                
                # NEW: Bind click event to LabelFrame itself to open transmitter folder
                # Pass feed_index for existing live feed click functionality
                frame.bind("<Button-1>", lambda e, idx=feed_index: self._open_transmitter_folder(feed_index=idx))
                # Need to also bind to the label and all its children so clicks anywhere on the live feed area open the folder
                label.bind("<Button-1>", lambda e, idx=feed_index: self._open_transmitter_folder(feed_index=idx))
                # If there are any other widgets inside the frame, bind them too

        # --- Rightmost Column: Transmission Details ---
        rightmost_panel_container = tb.Frame(self.master, relief="flat", borderwidth=0)
        rightmost_panel_container.grid(row=1, column=1, sticky="nswe", padx=(0, self.PADDING_X), pady=(0, self.PADDING_Y))
        rightmost_panel_container.grid_columnconfigure(0, weight=1)
        rightmost_panel_container.grid_rowconfigure(0, weight=1) # Only one row for info_frame

        # Transmitted Location & Info - LabelFrame with light green title
        info_frame = tb.LabelFrame(rightmost_panel_container, text="📊 Transmission Details", bootstyle="GreenTitle.TLabelframe")
        info_frame.grid(row=0, column=0, sticky="nswe", padx=(0, self.PADDING_X), pady=self.PADDING_Y // 2) # sticky "nswe" to fill the whole column
        info_frame.grid_propagate(False) # Prevent shrinking
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_rowconfigure(0, weight=1) # Make sure the label can expand

        self.received_info_label = tb.Label(info_frame, text=self._get_initial_info_text(),
                                             font=("Segoe UI", 10), foreground="#33CC33", wraplength=250, justify="left")
        self.received_info_label.grid(row=0, column=0, sticky="nsew", padx=10, pady=5) # Use grid for label within info_frame

        # Removed Visualisation and Event Log sections as per request

    def _open_live_feed_detail_screen(self, feed_index):
        # Create a new Toplevel window for the detailed view
        detail_window = tb.Toplevel(self.master)
        transmitter_name = self.live_feed_assignments[feed_index]['transmitter_name']
        detail_window.title(f"Live Feed {feed_index + 1} - Detailed View ({transmitter_name})")
        detail_window.geometry("800x600") # A reasonable size for a detailed view
        detail_window.transient(self.master) # Make it appear on top of the main window
        detail_window.grab_set() # Make it modal

        detail_window.grid_columnconfigure(0, weight=1)
        detail_window.grid_rowconfigure(0, weight=1) # Image display area
        detail_window.grid_rowconfigure(1, weight=0) # Buttons area

        # Image display area in the detailed view
        detail_image_label = tb.Label(detail_window, text="No Image", anchor="center", font=("Segoe UI", 16), background="black", foreground="white")
        detail_image_label.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        # Display the current image from the selected feed
        current_image_data = self.live_feed_assignments[feed_index]['last_image_data']
        if current_image_data is not None:
            # We'll use a larger size for the detailed view
            self._display_image_in_label(detail_image_label, current_image_data, (780, 500)) 
        else:
            detail_image_label.config(text="No live image received yet for this feed.")
            detail_image_label.image = None # Clear any previous image reference

        # Buttons frame at the bottom (Only Close button remains)
        button_frame = tb.Frame(detail_window)
        button_frame.grid(row=1, column=0, sticky="ew", pady=10, padx=10)
        button_frame.grid_columnconfigure(0, weight=1) # Only one column for close button

        tb.Button(button_frame, text="Close", command=detail_window.destroy, bootstyle="danger").grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        # Set focus to the new window and wait for it to close
        detail_window.wait_window()
        self._log_event(f"Detailed view for Live Feed {feed_index + 1} closed.")

    # Removed _capture_displayed_image and _auto_capture_detailed_view_action as they are no longer needed


    # --- Canvas Configuration Helper (no longer directly used for 'All Images Displayed' as it's removed) ---
    def _on_canvas_configure(self, event):
        # This function is no longer relevant for the new layout but kept as a placeholder if needed for other canvases
        if self.all_images_canvas and self.all_images_inner_frame_id:
            self.all_images_canvas.configure(scrollregion = self.all_images_canvas.bbox("all"))
            canvas_width = event.width
            scrollbar_width_approx = 20 + self.SCROLLBAR_PAD
            self.all_images_canvas.itemconfig(self.all_images_inner_frame_id, width=canvas_width - scrollbar_width_approx)


    # --- Shared Image Display Helper ---
    def _display_image_in_label(self, label_widget, cv2_frame, target_size=None):
        if cv2_frame is None or cv2_frame.shape[0] == 0 or cv2_frame.shape[1] == 0:
            label_widget.config(image='', text="No Image Available", foreground="gray")
            label_widget.image = None
            return

        # Use the label's actual dimensions if available, otherwise fall back to target_size or defaults
        if label_widget.winfo_width() > 1 and label_widget.winfo_height() > 1:
            effective_target_size = (label_widget.winfo_width(), label_widget.winfo_height())
        elif target_size:
            effective_target_size = target_size
        else:
            effective_target_size = (self.DISPLAY_AREA_WIDTH, self.DISPLAY_AREA_HEIGHT)

        # Ensure dimensions are positive
        if effective_target_size[0] <= 0: effective_target_size = (self.DISPLAY_AREA_WIDTH, effective_target_size[1])
        if effective_target_size[1] <= 0: effective_target_size = (effective_target_size[0], self.DISPLAY_AREA_HEIGHT)

        cv2image = cv2.cvtColor(cv2_frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(cv2image)
        
        # Resize while maintaining aspect ratio to fit within the target_size
        img.thumbnail(effective_target_size, Image.LANCZOS)

        imgtk = ImageTk.PhotoImage(image=img)
        label_widget.imgtk = imgtk
        label_widget.config(image=imgtk, text="", foreground="black")

    # MODIFIED: New function to update live feed display based on transmitter name
    def _update_live_feed_display(self, transmitter_name, cv2_image):
        assigned_to_feed_index = -1

        # Define preferred assignments for specific transmitter names
        # This allows you to map specific TX names to specific live feed display slots.
        # For example, if you want "Tx1" to always go to Live Feed 1 (index 0)
        # and "Tx2" to Live Feed 2 (index 1), set them here.
        preferred_assignments = {
            "Tx1": 0, 
            "Tx2": 1, 
            # Add more specific TxName: index mappings if needed
        }

        # 1. Check if this transmitter has a preferred slot and if it's available or already assigned to it
        if transmitter_name in preferred_assignments:
            preferred_idx = preferred_assignments[transmitter_name]
            # Check if the preferred slot is available ('N/A') or already assigned to *this* transmitter
            if self.live_feed_assignments[preferred_idx]['transmitter_name'] in ['N/A', transmitter_name]:
                assigned_to_feed_index = preferred_idx
                self._log_event(f"Assigned {transmitter_name} to its preferred Live Feed {assigned_to_feed_index + 1}.")
        
        # 2. If not assigned by preference, check if this transmitter is already assigned to *any* feed
        #    This is important for continuous updates to an already established feed.
        if assigned_to_feed_index == -1:
            for i, feed in enumerate(self.live_feed_assignments):
                if feed['transmitter_name'] == transmitter_name:
                    assigned_to_feed_index = i
                    self._log_event(f"Re-assigned {transmitter_name} to its existing Live Feed {assigned_to_feed_index + 1}.")
                    break

        # 3. If still not assigned, find an available ('N/A') slot that is NOT a preferred slot for another specific transmitter.
        #    This helps keep preferred slots open for their intended transmitters if they haven't connected yet.
        if assigned_to_feed_index == -1:
            for i, feed in enumerate(self.live_feed_assignments):
                # Check if it's N/A AND if this slot index is NOT one of the values in preferred_assignments
                if feed['transmitter_name'] == 'N/A' and i not in preferred_assignments.values():
                    assigned_to_feed_index = i
                    self._log_event(f"Assigned {transmitter_name} to general available Live Feed {assigned_to_feed_index + 1}.")
                    break
        
        # 4. Fallback: If all specific slots and general available slots are taken,
        #    find the first truly 'N/A' slot (even if it's a preferred slot for another TX that hasn't connected)
        #    or overwrite the first slot (index 0) as a last resort.
        if assigned_to_feed_index == -1:
            # First, check for any 'N/A' slot, even preferred ones if they are truly empty.
            for i, feed in enumerate(self.live_feed_assignments):
                if feed['transmitter_name'] == 'N/A':
                    assigned_to_feed_index = i
                    self._log_event(f"Fallback: Assigned {transmitter_name} to Live Feed {assigned_to_feed_index + 1} (it was 'N/A').")
                    break
            
            # If no 'N/A' slots are found (meaning all 4 are occupied by distinct transmitters), overwrite slot 0
            if assigned_to_feed_index == -1:
                assigned_to_feed_index = 0 
                self._log_event(f"All live feed slots occupied by distinct transmitters. Overwriting Live Feed {assigned_to_feed_index + 1} with {transmitter_name}.")


        # Update the chosen feed slot if an assignment was made
        if assigned_to_feed_index != -1:
            feed_slot = self.live_feed_assignments[assigned_to_feed_index]
            feed_slot['transmitter_name'] = transmitter_name
            feed_slot['last_image_data'] = cv2_image
            
            # Update the label and its parent LabelFrame text on the main thread
            self.master.after(0, lambda: self._display_image_in_label(feed_slot['label_widget'], cv2_image, (self.DISPLAY_AREA_WIDTH, self.DISPLAY_AREA_HEIGHT)))
            self.master.after(0, lambda: feed_slot['label_frame_widget'].config(text=f"Live feed {assigned_to_feed_index + 1}: {transmitter_name}"))
        else:
            self._log_event(f"WARNING: Could not assign {transmitter_name} to any live feed display.")


    # This method is no longer used for image filtering in the new layout
    def _update_display_for_selected_tx(self, event=None):
        pass # This function's logic is now superseded by the new live feed display

    def _on_transmitter_filter_changed(self, event):
        # This combobox is removed from the main GUI
        self._log_event(f"Transmitter filter changed to: {self.selected_transmitter_filter.get()} (Combobox is now hidden)")
        # self._update_display_for_selected_tx()

    def _show_specific_image(self, image_path, transmitter_name, timestamp):
        # This function is no longer directly callable from the main GUI due to layout change
        try:
            cv2_img = cv2.imread(image_path)
            if cv2_img is not None and cv2_img.size > 0:
                # Decide which live feed label to update, e.g., the first one
                # MODIFIED: Now uses the new _update_live_feed_display
                self._update_live_feed_display(transmitter_name, cv2_img)
                
                self.received_info_label.config(text=(
                    f"Images Received (Total): {len(self.all_received_images_metadata)}\n"
                    f"Selected image: {os.path.basename(image_path)}\n"
                    f"Transmitter: {transmitter_name}\n"
                    f"Time: {timestamp.strftime('%H:%M:%S')}"
                ))
                self._log_event(f"Displayed image: {os.path.basename(image_path)} from {transmitter_name}")
            else:
                self._log_event(f"ERROR: Could not load image for display: {image_path}")
        except Exception as e:
            self._log_event(f"ERROR: An error occurred displaying image {image_path}: {e}")

    # --- Utility/Log Functions ---
    def _get_initial_info_text(self):
        return (f"Date: {datetime.datetime.now().strftime('%Y-%m-%d')}\n"
                f"Time: {datetime.datetime.now().strftime('%H:%M:%S')}\n"
                f"Status: Waiting for connection...\n"
                f"Transmitter Name: N/A")

    def _update_received_info_display(self, img_count, total_frames, status_msg, transmitter_name="N/A"):
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')
        current_time = datetime.datetime.now().strftime('%H:%M:%S')
        text = (f"Date: {current_date}\n"
                f"Time: {current_time}\n"
                f"Status: {status_msg}\n"
                f"Transmitter Name: {transmitter_name}") # Use provided transmitter_name
        self.received_info_label.config(text=text)

    def _update_server_status_display(self):
        # MODIFIED: Server status display now reflects actual server_running state
        if self.server_running:
            self.server_status_label.config(text="Server Status: ONLINE", bootstyle="StatusOnline.TLabel")
        else:
            self.server_status_label.config(text="Server Status: OFFLINE", bootstyle="StatusOffline.TLabel")


    def _log_event(self, message):
        timestamp = datetime.datetime.now().strftime('%H:%M:%S')
        log_entry = f"[{timestamp}] {message}"
        # Removed: self.master.after(0, self.__update_log_text_widget, log_entry)
        # Event log is removed from GUI, so direct print to console.
        print(log_entry)

    # Removed __update_log_text_widget as it's no longer needed

    def show_output_folder(self):
        # Both buttons now open the single consolidated output folder
        try:
            subprocess.Popen(['explorer', receiver_output_base_folder]) # For Windows
            # For macOS: subprocess.Popen(['open', receiver_output_base_folder])
            # For Linux: subprocess.Popen(['xdg-open', receiver_output_base_folder])
            self._log_event(f"Opened consolidated output folder: {receiver_output_base_folder}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open output folder: {e}")
            self._log_event(f"ERROR: Could not open output folder: {e}")

    # NEW: Function to open a specific transmitter's folder, now accepts feed_index or transmitter_name
    def _open_transmitter_folder(self, feed_index=None, transmitter_name=None):
        actual_transmitter_name = None
        if feed_index is not None:
            # Logic for clicks on live feed displays
            actual_transmitter_name = self.live_feed_assignments[feed_index]['transmitter_name']
            if actual_transmitter_name == 'N/A':
                self._log_event(f"Cannot open folder for Live Feed {feed_index + 1}: No transmitter assigned yet.")
                return
        elif transmitter_name is not None:
            # Logic for new TX buttons
            actual_transmitter_name = transmitter_name
        else:
            self._log_event("Error: _open_transmitter_folder called without feed_index or transmitter_name.")
            return

        tx_folder_path = os.path.join(receiver_output_base_folder, actual_transmitter_name)
        
        if not os.path.exists(tx_folder_path):
            self._log_event(f"Folder for {actual_transmitter_name} does not exist yet: {tx_folder_path}")
            # Optionally create it if it doesn't exist, or just log/inform user
            # os.makedirs(tx_folder_path, exist_ok=True)
            # self._log_event(f"Created folder for {actual_transmitter_name}: {tx_folder_path}")

        try:
            subprocess.Popen(['explorer', tx_folder_path]) # For Windows
            # For macOS: subprocess.Popen(['open', tx_folder_path])
            # For Linux: subprocess.Popen(['xdg-open', tx_folder_path])
            self._log_event(f"Opened folder for transmitter {actual_transmitter_name}: {tx_folder_path}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open folder for {actual_transmitter_name}: {e}")
            self._log_event(f"ERROR: Could not open folder for {actual_transmitter_name}: {e}")


    def show_settings_view(self):
        self._log_event("Opened Settings & About dialog (content sent to log, no popup).")

    def exit_application(self):
        if messagebox.askyesno("Exit", "Are you sure you want to exit the application?"):
            self._log_event("Exiting application...")
            self.stop_server()
            self.master.destroy()
            sys.exit(0)

if __name__ == "__main__":
    try:
        import numpy as np
    except ImportError:
        print("Numpy not found. Please install it: pip install numpy")
        sys.exit(1)

    app_style = tb.Style('litera')
    root = app_style.master

    # Corrected the style application for the Exit button
    app_style.configure("GreenTitle.TLabelframe.Label", foreground="#33CC33", font=("Segoe UI", 12))
    app_style.configure("StatusOnline.TLabel", background="#E6FFE6", foreground="green", font=("Segoe UI", 12, "bold"))
    app_style.configure("StatusOffline.TLabel", background="#FFCCCC", foreground="red", font=("Segoe UI", 12, "bold"))
    
    # Define a custom style for the Exit button to apply font settings
    # The font property is set on the style itself, not directly on the button widget
    app_style.configure("BigDanger.TButton", font=("Segoe UI", 12, "bold"))

    app = ReceiverApp(root)
    root.mainloop()