Frame-Based Image Transmission and Reception System

📌 Project Overview

This project focuses on designing and implementing a real-time image transmission and reconstruction system over a local area network (LAN) using Python socket programming.

The system captures images from a webcam (or allows manual file selection), compresses them, splits them into frame-wise chunks, and sends them across the network. Each frame carries a custom 10-byte header containing metadata like frame index, row/column position, and total frame count.

On the receiving side, the application listens for incoming data, extracts the metadata, reconstructs the full image by mapping chunks in the correct order, and fills missing frames with placeholders if needed.

Both transmitter and receiver have graphical user interfaces (GUI) built using Tkinter and ttkbootstrap, providing a simple yet powerful environment for real-time monitoring, error tracking, and logging.

This project demonstrates how low-level networking concepts can be used to build a WhatsApp-like image sharing protocol at the system level.

📖 Introduction

In modern digital communication, real-time image transmission plays an important role in messaging, surveillance, satellite communication, and remote sensing.
Unlike normal file transfers, this project simulates how communication systems split an image into smaller frames to:

Improve reliability

Handle errors gracefully

Work under limited bandwidth

The main contributions of this project are:

Frame-based transmission protocol with metadata headers.

Real-time reconstruction with missing frame handling.

GUI interfaces for interactive visualization and control.

Extensible modular design for future use in satellite and mobile communication.

✨ Key Features
🔹 Transmitter Module

Captures live images from webcam or selects stored images.

Compresses images using JPEG at fixed quality (40%) for balance of size and clarity.

Splits into multiple frames (~90 bytes per chunk + 10-byte header).

Sends frames sequentially over TCP/IP sockets.

Supports three operational modes:

Manual Mode – user captures and sends images manually.

Timer-Based Mode – automated sending at scheduled intervals (e.g., every 15 min).

Continuous Mode – real-time streaming by sending frames continuously.

 Frames:

 <img width="608" height="403" alt="image" src="https://github.com/user-attachments/assets/9925dfbc-f079-46ee-9710-06f23e5b4585" />


GUI Features:

Live camera preview

Frame size adjustment (80–100 bytes)

Transmission progress bar

Real-time logs of sent frames

🔹 Receiver Module

Runs a TCP server to accept connections.

Extracts metadata from headers to reassemble frames.

Detects missing frames and replaces them with black placeholders.

Reconstructs full image using OpenCV.

GUI Features:

Live preview of last received image

Image history categorized by transmitter ID

Transmission statistics (frames received, missing frames, total size)

Logs and alerts for errors or missing data

🛠️ Tools & Technologies

Language: Python 3.10+

Libraries:

OpenCV → image compression & decoding

NumPy → array & data handling

PIL (Pillow) → image processing

socket → TCP/IP communication

GUI Framework: Tkinter + ttkbootstrap (modern design), PAGE (for layout)

Extra Modules: threading & multiprocessing (smooth performance)

Hardware Used: Webcam (USB), LAN/Wi-Fi connection

IDE: Visual Studio Code

🏗️ System Architecture
Transmitter Workflow

Capture/Select image.

Compress using JPEG encoding (quality 40%).

Convert image into byte stream.

Divide into multiple frames (each ~90 bytes + 10-byte header).

Attach metadata header with:

Frame Index

Row Index

Column Index

Total Frame Count

Reserved Padding

Send frames over socket connection.

Receiver Workflow

Start server and accept incoming frames.

Extract metadata from headers.

Reassemble frames into structured grid.

Handle missing frames by inserting placeholders.

Reconstruct full image using OpenCV.

Display reconstructed image in GUI and store in organized folders.

📊 Experimental Results

Average Transmission Time: ~2.3 seconds per image (Wi-Fi)

Slightly faster using Ethernet.

Decoding Accuracy: 100% when all frames are received.

Missing Frames Handling: Black placeholders preserve structure.

GUI Latency: Minimal delay between sending and preview updates.

Auto Modes: Timer and continuous modes worked smoothly without errors.

This shows the system can reliably transmit images over LAN even with packet/frame loss.

⚠️ Challenges & Limitations

Frame Loss: Network delays may drop frames; handled with placeholders but not perfect.

Fixed JPEG Quality: Only one compression level (40%); no adaptive encoding yet.

Still Images Only: No live video streaming yet.

GUI Performance: May slow with too many images in history.

Static IP Requirement: Currently designed for LAN only.

🔮 Future Enhancements

Add live video streaming support.

Integrate AES encryption for secure data transfer.

Enable cloud storage of received images.

Add mobile app for remote access.

Replace TCP with WebSocket / MQTT protocols for IoT integration.

Optimize system for satellite and underwater communication with frame size between 55–110 bytes.

📥 Installation

Install dependencies:

pip install opencv-python numpy pillow ttkbootstrap  

▶️ Usage
Start Receiver
python receiver.py  


Starts TCP server

Displays reconstructed images in GUI

Start Transmitter
python transmitter.py  


Opens GUI

Capture/send images in manual, timer, or continuous mode

📌 Applications

WhatsApp-like image transfer at protocol level

Remote surveillance and security systems

Satellite-based data reception

Underwater monitoring and exploration

Offline image sharing in low-bandwidth environments

💻GUI Ouput

Transmitter:

<img width="880" height="510" alt="image" src="https://github.com/user-attachments/assets/c12c73a2-1bfb-4ad8-8065-c8b8bc485490" />

Receiver:

<img width="837" height="433" alt="image" src="https://github.com/user-attachments/assets/8de089ca-3044-4e70-b471-08ed093e7c8e" />

👨‍💻 Author

Developed as part of an academic project on Real-Time Communication Systems.
