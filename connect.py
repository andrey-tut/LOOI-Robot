import asyncio
import sys
import termios
import tty
import time
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

# --- CONFIG ---
NAME_CONTAINS = "LOOI"

# UUIDs
CHAR_MOVE    = "0000fed0-0000-1000-8000-00805f9b34fb"
CHAR_SENS    = "0000fed5-0000-1000-8000-00805f9b34fb"
CHAR_BATTERY = "0000fed8-0000-1000-8000-00805f9b34fb"
CHAR_STREAM  = "0000fed9-0000-1000-8000-00805f9b34fb"
CHAR_FEDA    = "0000feda-0000-1000-8000-00805f9b34fb"
UUID_MANUFACTURER = "00002a29-0000-1000-8000-00805f9b34fb"

# --- KEYBOARD INPUT ---
def get_key():
    try:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except: return None

# --- MACOS FIX ---
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
        print("CONNECTED! Initializing...")
        await asyncio.sleep(1.0)

        if not await ensure_services(client):
            print("ERROR: Bluetooth services not ready.")
            return

        # --- HANDSHAKE SEQUENCE ---
        try:
            print(" -> Handshake 1 (0x01)...")
            await client.write_gatt_char(CHAR_FEDA, b"\x01", response=True)

            print(" -> Subscribing...")
            for uuid in [CHAR_SENS, CHAR_STREAM]:
                try: await client.start_notify(uuid, lambda s, d: None)
                except: pass

            print(" -> Handshake 2 (0x03)...")
            await client.write_gatt_char(CHAR_FEDA, b"\x03", response=True)
            print(" -> ROBOT ACTIVATED!")
        except Exception as e:
            print(f"Error during init: {e}")
            return

        print("\n" + "="*40)
        print("      🏎️  LOOI RACE MODE  🏎️")
        print("="*40)
        print(" Тримай W/S/A/D щоб їхати.")
        print(" Відпусти кнопку - робот зупиниться.")
        print(" Q = Вихід")
        print("="*40 + "\n")

        # Shared state
        # Використовуємо mutable list, щоб змінювати його з різних функцій
        state = {
            "cmd": b"\x00\x00",
            "last_press": time.time(),
            "running": True
        }

        # --- TASK A: MOTION & AUTO-STOP ---
        async def motion_loop():
            while state["running"]:
                try:
                    # АВТО-СТОП: Якщо кнопку не натискали 0.15 сек - зупиняємось
                    if time.time() - state["last_press"] > 0.15:
                        state["cmd"] = b"\x00\x00"

                    await client.write_gatt_char(CHAR_MOVE, state["cmd"], response=False)
                    await asyncio.sleep(0.03) # 30ms interval
                except:
                    await asyncio.sleep(0.1)

        # --- TASK B: BATTERY KEEPALIVE ---
        async def battery_loop():
            while state["running"]:
                try:
                    await client.read_gatt_char(CHAR_BATTERY)
                    await asyncio.sleep(4.0)
                except:
                    await asyncio.sleep(2.0)

        asyncio.create_task(motion_loop())
        asyncio.create_task(battery_loop())

        # --- MAIN INPUT LOOP ---
        while state["running"]:
            key = await asyncio.to_thread(get_key)
            if not key: break
            key = key.lower()

            # Оновлюємо час останнього натискання
            state["last_press"] = time.time()

            if key == 'q':
                state["running"] = False
                break

            # МАКСИМАЛЬНА ШВИДКІСТЬ (0x7F = 127, 0x81 = -127)
            elif key == 'w':
                # ВПЕРЕД MAX
                state["cmd"] = b"\x7F\x00"
            elif key == 's':
                # НАЗАД MAX (0x81 це -127 у signed int8)
                state["cmd"] = b"\x81\x00"
            elif key == 'a':
                # ВЛІВО MAX (крутитися)
                state["cmd"] = b"\x00\x7F"
            elif key == 'd':
                # ВПРАВО MAX (крутитися)
                state["cmd"] = b"\x00\x81"

        # Final Stop
        try:
            await client.write_gatt_char(CHAR_MOVE, b"\x00\x00", response=False)
        except: pass

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt: pass
    print("\nDisconnected.")
