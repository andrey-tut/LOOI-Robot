import asyncio
import sys
import termios
import tty
import select
import time
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# --- CONFIG ---
NAME_CONTAINS = "LOOI"

# UUIDs
CHAR_MOVE    = "0000fed0-0000-1000-8000-00805f9b34fb"  # [Speed, Turn]
CHAR_HEAD    = "0000fed1-0000-1000-8000-00805f9b34fb"  # [Angle]
CHAR_SENS    = "0000fed5-0000-1000-8000-00805f9b34fb"  # Sensors Notify
CHAR_BATTERY = "0000fed8-0000-1000-8000-00805f9b34fb"  # Battery Read
CHAR_STREAM  = "0000fed9-0000-1000-8000-00805f9b34fb"  # Telemetry Notify
CHAR_FEDA    = "0000feda-0000-1000-8000-00805f9b34fb"  # Handshake
UUID_MANUF   = "00002a29-0000-1000-8000-00805f9b34fb"  # Device Info (Wakeup Mac)

# --- NON-BLOCKING KEY INPUT ---
def is_data():
    return select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], [])

async def ensure_services(client):
    print(" -> [System] Waiting for macOS Service Discovery...")
    for i in range(10):
        try:
            _ = client.services 
            print(" -> [System] Services mapped successfully!")
            return True
        except BleakError:
            await asyncio.sleep(0.5)
    return False

async def main():
    print(f"Searching for '{NAME_CONTAINS}'...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, a: NAME_CONTAINS.lower() in (d.name or "").lower()
    )
    if not device:
        print("Not found.")
        return

    print(f"Connecting to {device.address}...")
    
    async with BleakClient(device.address, timeout=20.0) as client:
        print("CONNECTED! Initializing Protocol...")
        
        # 1. Wake up macOS Bluetooth cache
        try: await client.read_gatt_char(UUID_MANUF)
        except: pass
        
        if not await ensure_services(client):
            print("ERROR: Bluetooth services failure.")
            return

        # 2. Handshake 1
        print(" -> Handshake 1...")
        await client.write_gatt_char(CHAR_FEDA, b"\x01", response=True)
        await asyncio.sleep(0.1)

        # 3. Subscribe (Critical for staying alive)
        print(" -> Subscribing...")
        for uuid in [CHAR_SENS, CHAR_STREAM]:
            try: await client.start_notify(uuid, lambda s, d: None)
            except: pass

        # 4. Handshake 2 (Activation)
        print(" -> Handshake 2...")
        await client.write_gatt_char(CHAR_FEDA, b"\x03", response=True)
        print(" -> ROBOT READY!")

        # --- SETUP TERMINAL ---
        old_settings = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())

            print("\n" + "="*40)
            print("      🚀 LOOI ULTIMATE CONTROL 🚀")
            print("="*40)
            print(" [W] Forward (MAX)   [I] Head Up")
            print(" [S] Backward (MAX)  [K] Head Down")
            print(" [A] Left Spin       [Q] QUIT")
            print(" [D] Right Spin")
            print(" (Release key to STOP)")
            print("="*40 + "\n")

            # --- STATE ---
            move_cmd = b"\x00\x00"
            head_pos = 0x5A # 90 degrees (Center)
            last_key_time = 0
            running = True

            # --- BACKGROUND TASKS ---
            async def sender_loop():
                while running:
                    try:
                        # Send Movement (Every 30ms)
                        await client.write_gatt_char(CHAR_MOVE, move_cmd, response=False)
                        
                        # Send Head (only if needed, but keeping it simple)
                        # Uncomment to control head continuously if needed
                        # await client.write_gatt_char(CHAR_HEAD, bytes([head_pos]), response=False)
                        
                        await asyncio.sleep(0.03)
                    except:
                        await asyncio.sleep(0.1)

            async def battery_loop():
                while running:
                    try:
                        await client.read_gatt_char(CHAR_BATTERY)
                        await asyncio.sleep(4.0)
                    except:
                        await asyncio.sleep(2.0)

            asyncio.create_task(sender_loop())
            asyncio.create_task(battery_loop())

            # --- MAIN INPUT LOOP ---
            while running:
                if is_data():
                    key = sys.stdin.read(1).lower()
                    last_key_time = time.time()

                    if key == 'q':
                        running = False
                        break
                    
                    # MOVEMENT (Max Speed 0x7F / 0x81)
                    elif key == 'w':
                        move_cmd = b"\x7F\x00" # Fwd Max
                        print("\r ▲▲▲ ", end="")
                    elif key == 's':
                        move_cmd = b"\x81\x00" # Back Max (-127)
                        print("\r ▼▼▼ ", end="")
                    elif key == 'a':
                        move_cmd = b"\x00\x7F" # Left Spin
                        print("\r ◄◄◄ ", end="")
                    elif key == 'd':
                        move_cmd = b"\x00\x81" # Right Spin (-127)
                        print("\r ►►► ", end="")
                    
                    # HEAD CONTROL
                    elif key == 'i':
                        head_pos = min(0xFF, head_pos + 10)
                        await client.write_gatt_char(CHAR_HEAD, bytes([head_pos]), response=False)
                        print(f"\r Head: {head_pos} ", end="")
                    elif key == 'k':
                        head_pos = max(0x00, head_pos - 10)
                        await client.write_gatt_char(CHAR_HEAD, bytes([head_pos]), response=False)
                        print(f"\r Head: {head_pos} ", end="")

                else:
                    # AUTO-STOP: If no key pressed for 0.1s
                    if time.time() - last_key_time > 0.1 and move_cmd != b"\x00\x00":
                        move_cmd = b"\x00\x00"
                        print("\r  🛑   ", end="")
                
                await asyncio.sleep(0.01) # Poll interval

        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            try:
                await client.write_gatt_char(CHAR_MOVE, b"\x00\x00", response=False)
            except: pass
            print("\nDisconnected.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
