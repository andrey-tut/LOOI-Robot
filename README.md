# LOOI-Robot

This repository contains my experiments with the LOOI Robot. I found the stock application too primitive, so I decided to reverse-engineer the Bluetooth LE protocol to control the robot base directly using Python.

Based on packet sniffer logs, I successfully mapped the movement commands, status reports, and the specific initialization sequence required to keep the robot active.

Features:

✅ Full Movement Control: Forward/Backward/Spin (Drift Mode) with variable speed support.

✅ Head Control: Adjusting the head angle.

✅ Stable Connection: Implemented the specific "Double Handshake" and battery polling heartbeat required to prevent the robot from disconnecting.

✅ macOS Support: Includes fixes for bleak service discovery issues on macOS.

Goal: This is a Proof of Concept. The goal is to enable the community to build better, more advanced applications for LOOI than the default stock app.

🛠️ Technical Details (The Protocol)
If you want to build your own app, here is what I found during the reverse engineering process:

1. Key UUIDs
Move (Write): 0000fed0-0000-1000-8000-00805f9b34fb

Head (Write): 0000fed1-0000-1000-8000-00805f9b34fb

Handshake/Settings (Write): 0000feda-0000-1000-8000-00805f9b34fb

Battery/Status (Read): 0000fed8-0000-1000-8000-00805f9b34fb

Sensors (Notify): 0000fed5-0000-1000-8000-00805f9b34fb

2. Initialization Sequence (Critical)
The robot has an aggressive watchdog timer. To keep it alive, you must follow this sequence exactly:

Connect via BLE.

Handshake 1: Write 0x01 to FEDA.

Subscribe: Enable notifications on FED5 (Sensors) and FED9 (Telemetry).

Handshake 2: Write 0x03 to FEDA. Without this, the robot accepts commands but disconnects after a few seconds.

3. Movement Protocol (FED0)
The payload consists of 2 bytes: [Speed, Turn]. Values are Signed Int8 (-127 to +127).

0x7F (127) = Max Forward / Max Left.

0x81 (-127) = Max Backward / Max Right.

Heartbeat: You must send a movement packet (even 00 00) every ~30ms, otherwise the motors disengage.

4. Keep-Alive (Battery)
The official app reads the Battery Characteristic (FED8) approximately every 4-5 seconds. If this read request is missing for too long, the robot might assume the app has crashed and disconnect.

💻 Requirements
Python 3.10+

bleak library

Bash

pip install bleak
🎮 Usage
Run the script to control the robot with your keyboard:

Bash

python looi_drift_fix.py
W / S: Forward / Backward (Max speed)

A / D: Left / Right (Mixable with W/S for drifting)

I / K: Head Up / Down

Q: Quit

Disclaimer: This is an unofficial project. Use at your own risk. I am not affiliated with the LOOI Robot manufacturers.
