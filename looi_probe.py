import asyncio
import csv
import time
from dataclasses import dataclass
from typing import Optional, List

from bleak import BleakClient, BleakScanner

# ================== CONFIG ==================
ADDRESS: Optional[str] = None        # set MAC from LightBlue for stability
NAME_CONTAINS = "LOOI"

CHAR_MOVE  = "0000fed0-0000-1000-8000-00805f9b34fb"
CHAR_HEAD  = "0000fed1-0000-1000-8000-00805f9b34fb"
CHAR_LIGHT = "0000fed2-0000-1000-8000-00805f9b34fb"
CHAR_SENS  = "0000fed5-0000-1000-8000-00805f9b34fb"
CHAR_STREAM= "0000fed9-0000-1000-8000-00805f9b34fb"

LOG_FILE = "looi_lab.csv"

# We don't know stop. We'll try these (very common)
STOP_PAYLOADS = [b"\x00", b"\x10\x00", b"\xFF"]

# Safety: any sensor notify => stop immediately (until we decode bits)
STOP_ON_ANY_SENSOR_ACTIVITY = True

# Timing
ACTION_TIME = 0.30     # how long to let command act
PAUSE_BETWEEN = 0.25   # pause after stop
# ============================================


@dataclass
class Case:
    payload: bytes
    note: str


def now_iso() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def ensure_csv():
    try:
        with open(LOG_FILE, "r", encoding="utf-8"):
            return
    except FileNotFoundError:
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time", "payload_hex", "note", "result"])


def log_case(c: Case, result: str):
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([now_iso(), c.payload.hex(), c.note, result])


async def find_addr() -> str:
    if ADDRESS:
        return ADDRESS
    devices = await BleakScanner.discover(timeout=6)
    for d in devices:
        if (d.name or "").lower().find(NAME_CONTAINS.lower()) >= 0:
            return d.address
    raise RuntimeError("LOOI not found. Set ADDRESS manually from LightBlue.")


class SafetyState:
    def __init__(self):
        self.sensor_last = b""
        self.sensor_activity = False

    def reset(self):
        self.sensor_activity = False


async def stop(client: BleakClient):
    # Try multiple stop encodings
    for p in STOP_PAYLOADS:
        try:
            await client.write_gatt_char(CHAR_MOVE, p, response=False)
            await asyncio.sleep(0.03)
        except Exception:
            pass


def mk_cases_mode1_singlebyte() -> List[Case]:
    # You already know 0x10 works.
    # We'll still try neighbors and some "common" opcodes, but you've likely tried many.
    # Keep it small so you don't waste time.
    interesting = [
        0x00, 0x01, 0x02, 0x03,
        0x0F, 0x10, 0x11, 0x12, 0x13,
        0x14, 0x15,
        0x1F, 0x20, 0x21, 0x22, 0x23,
        0x30, 0x31, 0x32, 0x33,
        0x40, 0x41, 0x42, 0x43,
        0x7F, 0x80, 0xFF,
    ]
    return [Case(bytes([b]), "MOVE: 1-byte opcode probe") for b in interesting]


def mk_cases_mode2_cmd_speed() -> List[Case]:
    # Most likely: [cmd][speed]
    # We'll test a few cmd candidates with multiple speeds.
    cmds = [0x10, 0x11, 0x12, 0x13, 0x20, 0x21, 0x30, 0x31]
    speeds = [0x01, 0x08, 0x10, 0x20, 0x40, 0x60, 0x7F, 0xA0, 0xC0, 0xFF]
    out = []
    for cmd in cmds:
        for sp in speeds:
            out.append(Case(bytes([cmd, sp]), f"MOVE: [cmd=0x{cmd:02x}][speed=0x{sp:02x}]"))
    return out


def mk_cases_mode3_diff_drive() -> List[Case]:
    # Very common for small robots: [opcode][left][right]
    # We'll assume opcode 0x10 = "drive" and left/right are signed-ish or unsigned.
    # We'll test a safe small set.
    opcode = 0x10
    vals = [0x00, 0x10, 0x20, 0x40, 0x60, 0x7F, 0xA0, 0xC0, 0xFF]
    out = []
    for l in vals:
        for r in vals:
            if l == 0 and r == 0:
                continue
            out.append(Case(bytes([opcode, l, r]), f"MOVE: [0x10][L=0x{l:02x}][R=0x{r:02x}]"))
    return out


def mk_cases_mode4_speed_turn() -> List[Case]:
    # Another common: [cmd][speed][turn]
    # turn: 0x00 center, <0x80 left, >0x80 right OR signed.
    cmd = 0x10
    speeds = [0x10, 0x20, 0x40, 0x60, 0x7F]
    turns  = [0x00, 0x20, 0x40, 0x60, 0x7F, 0x80, 0xA0, 0xC0, 0xE0, 0xFF]
    out = []
    for sp in speeds:
        for t in turns:
            out.append(Case(bytes([cmd, sp, t]), f"MOVE: [0x10][speed=0x{sp:02x}][turn=0x{t:02x}]"))
    return out


async def main():
    ensure_csv()
    addr = await find_addr()
    print("LOOI:", addr)
    print("Log:", LOG_FILE)
    print("IMPORTANT: disconnect iPhone. LOOI allows only ONE controller at a time.\n")

    safety = SafetyState()

    def cb_sens(_sender: int, data: bytearray):
        safety.sensor_last = bytes(data)
        safety.sensor_activity = True
        print("NOTIFY FED5 (sensors):", data.hex())

    def cb_stream(_sender: int, data: bytearray):
        # spammy stream; keep it short
        print("NOTIFY FED9 (stream):", data.hex()[:80])

    def cb_ack0(_sender: int, data: bytearray):
        print("NOTIFY FED0:", data.hex())

    def cb_ack1(_sender: int, data: bytearray):
        print("NOTIFY FED1:", data.hex())

    # Choose mode here:
    # 1 = single-byte opcodes
    # 2 = [cmd][speed]
    # 3 = [0x10][L][R]
    # 4 = [0x10][speed][turn]
    mode = input("Mode (1/2/3/4) ? ").strip() or "2"

    if mode == "1":
        cases = mk_cases_mode1_singlebyte()
    elif mode == "2":
        cases = mk_cases_mode2_cmd_speed()
    elif mode == "3":
        cases = mk_cases_mode3_diff_drive()
    elif mode == "4":
        cases = mk_cases_mode4_speed_turn()
    else:
        print("Unknown mode")
        return

    async with BleakClient(addr) as client:
        print("Connected:", client.is_connected)

        # Subscribe to notifications (if supported)
        for cuuid, cb in [
            (CHAR_SENS, cb_sens),
            (CHAR_STREAM, cb_stream),
            (CHAR_MOVE, cb_ack0),
            (CHAR_HEAD, cb_ack1),
        ]:
            try:
                await client.start_notify(cuuid, cb)
                print("Notify ON:", cuuid)
            except Exception:
                pass

        await stop(client)

        for idx, c in enumerate(cases, start=1):
            print("=" * 70)
            print(f"[{idx}/{len(cases)}] SEND 0x{c.payload.hex()}  | {c.note}")
            cmd = input("ENTER=send | 'skip' | 'quit': ").strip().lower()
            if cmd == "quit":
                break
            if cmd == "skip":
                log_case(c, "SKIP")
                continue

            safety.reset()

            try:
                await client.write_gatt_char(CHAR_MOVE, c.payload, response=False)
                await asyncio.sleep(ACTION_TIME)

                # Safety stop if sensors fired
                if STOP_ON_ANY_SENSOR_ACTIVITY and safety.sensor_activity:
                    await stop(client)
                    await asyncio.sleep(PAUSE_BETWEEN)
                    res = input("Result (sensor fired -> stopped). What was movement before stop? ").strip() or "SENSOR_STOP"
                    log_case(c, res + f" | sens={safety.sensor_last.hex()}")
                    continue

                await stop(client)
                await asyncio.sleep(PAUSE_BETWEEN)

                res = input("What happened? (back/left/right/fwd fast/none): ").strip() or "NO_NOTE"
                log_case(c, res)

            except Exception as e:
                print("ERROR:", e)
                await stop(client)
                log_case(c, f"ERROR: {e}")

        await stop(client)
        print("\nDone.")

if __name__ == "__main__":
    asyncio.run(main())
