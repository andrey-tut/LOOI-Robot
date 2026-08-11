import argparse
import asyncio
import csv
import json
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError


NAME_CONTAINS = "LOOI"

CHAR_MOVE = "0000fed0-0000-1000-8000-00805f9b34fb"
CHAR_HEAD = "0000fed1-0000-1000-8000-00805f9b34fb"
CHAR_LIGHT = "0000fed2-0000-1000-8000-00805f9b34fb"
CHAR_SENS = "0000fed5-0000-1000-8000-00805f9b34fb"
CHAR_BATTERY = "0000fed8-0000-1000-8000-00805f9b34fb"
CHAR_STREAM = "0000fed9-0000-1000-8000-00805f9b34fb"
CHAR_FEDA = "0000feda-0000-1000-8000-00805f9b34fb"
CHAR_MANUFACTURER = "00002a29-0000-1000-8000-00805f9b34fb"


def now_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def signed_to_byte(value: int) -> int:
    value = max(-127, min(127, value))
    return value & 0xFF


def hex_bytes(data: bytes | bytearray) -> str:
    return bytes(data).hex()


def decode_fed9(data: bytes) -> str:
    if not data:
        return "empty"
    packet_type = data[0]
    if data == b"\x11\x01\x00":
        return "boot/init-complete"
    if packet_type == 0x01 and len(data) >= 5:
        return f"cliff/contact b1={data[1]} b2={data[2]} b3={data[3]} b4={data[4]}"
    if packet_type == 0x02 and len(data) >= 3:
        big = int.from_bytes(data[1:3], "big", signed=True)
        little = int.from_bytes(data[1:3], "little", signed=True)
        return f"imu-like int16be={big} int16le={little}"
    if packet_type == 0x09 and len(data) >= 2:
        return f"touch raw={data[1]}"
    return f"type=0x{packet_type:02x} len={len(data)}"


@dataclass
class ProbeCase:
    phase: str
    label: str
    target: str
    payload: bytes
    duration_s: float = 0.0
    note: str = ""


class ProbeLogger:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.root / "events.csv"
        self.results_path = self.root / "results.csv"
        self.summary_path = self.root / "summary.json"
        self._events = self.events_path.open("w", newline="", encoding="utf-8")
        self._results = self.results_path.open("w", newline="", encoding="utf-8")
        self.events = csv.writer(self._events)
        self.results = csv.writer(self._results)
        self.events.writerow(["t", "source", "hex", "decoded"])
        self.results.writerow(["t", "phase", "label", "target", "payload_hex", "duration_s", "note", "user_result"])
        self.summary: dict[str, object] = {
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "root": str(root),
        }

    def log_event(self, source: str, data: bytes, decoded: str = "") -> None:
        self.events.writerow([f"{time.time():.3f}", source, data.hex(), decoded])
        self._events.flush()

    def log_result(self, case: ProbeCase, user_result: str) -> None:
        self.results.writerow([
            f"{time.time():.3f}",
            case.phase,
            case.label,
            case.target,
            case.payload.hex(),
            f"{case.duration_s:.3f}",
            case.note,
            user_result,
        ])
        self._results.flush()

    def close(self) -> None:
        self.summary["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.summary_path.write_text(json.dumps(self.summary, indent=2, ensure_ascii=False), encoding="utf-8")
        self._events.close()
        self._results.close()


class LooiProbe:
    def __init__(self, client: BleakClient, logger: ProbeLogger, move_interval_s: float):
        self.client = client
        self.logger = logger
        self.move_interval_s = move_interval_s
        self.chars: dict[str, object] = {}
        self.move_payload = b"\x00\x00"
        self.running = True
        self.last_fed9_by_type: dict[int, bytes] = {}
        self.last_fed5: Optional[bytes] = None
        self.last_battery: Optional[bytes] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._battery_task: Optional[asyncio.Task] = None

    async def init(self) -> None:
        try:
            manufacturer = await self.client.read_gatt_char(CHAR_MANUFACTURER)
            self.logger.log_event("2A29", bytes(manufacturer), "manufacturer/device-info")
            print(f"2A29: {bytes(manufacturer).hex()} {bytes(manufacturer)!r}")
        except Exception as exc:
            print(f"2A29 read skipped: {exc}")

        await ensure_services(self.client)
        self._resolve_characteristics()

        print("INIT 1/3: FEDA <- 01")
        await self.write_char(CHAR_FEDA, b"\x01", response=True)
        await asyncio.sleep(0.1)

        print("INIT 2/3: subscribe FED5/FED9")
        await self.client.start_notify(self.char(CHAR_SENS), self._on_fed5)
        await self.client.start_notify(self.char(CHAR_STREAM), self._on_fed9)
        await asyncio.sleep(0.3)

        print("INIT 3/3: FEDA <- 03")
        await self.write_char(CHAR_FEDA, b"\x03", response=True)

        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._battery_task = asyncio.create_task(self._battery_loop())
        await self._health_check()
        print("READY: heartbeat FED0 every %.0fms, battery FED8 every 4s" % (self.move_interval_s * 1000))

    def _resolve_characteristics(self) -> None:
        required = [
            CHAR_MOVE,
            CHAR_HEAD,
            CHAR_LIGHT,
            CHAR_SENS,
            CHAR_BATTERY,
            CHAR_STREAM,
            CHAR_FEDA,
        ]
        services = self.client.services
        missing = []
        for uuid in required:
            characteristic = services.get_characteristic(uuid)
            if characteristic is None:
                missing.append(uuid)
            else:
                self.chars[uuid] = characteristic
        if missing:
            raise RuntimeError("Missing LOOI characteristics: " + ", ".join(missing))

    def char(self, uuid: str):
        characteristic = self.chars.get(uuid)
        if characteristic is None:
            raise RuntimeError(f"Characteristic not resolved: {uuid}")
        return characteristic

    async def write_char(self, uuid: str, payload: bytes, response: bool) -> None:
        if not self.client.is_connected:
            raise RuntimeError("BLE client is disconnected")
        await self.client.write_gatt_char(self.char(uuid), payload, response=response)

    async def read_char(self, uuid: str) -> bytes:
        if not self.client.is_connected:
            raise RuntimeError("BLE client is disconnected")
        return bytes(await self.client.read_gatt_char(self.char(uuid)))

    async def _health_check(self) -> None:
        for _ in range(3):
            await self.write_char(CHAR_MOVE, b"\x00\x00", response=False)
            await asyncio.sleep(0.04)
        battery = await self.read_char(CHAR_BATTERY)
        self.last_battery = battery
        decoded = f"battery percent?={battery[0]}" if battery else "empty"
        self.logger.log_event("FED8", battery, decoded)
        print(f"Health check OK: connected={self.client.is_connected}, FED8={battery.hex()} {decoded}")

    async def shutdown(self) -> None:
        self.running = False
        self.move_payload = b"\x00\x00"
        try:
            await self.write_char(CHAR_MOVE, b"\x00\x00", response=False)
        except Exception:
            pass
        for task in [self._heartbeat_task, self._battery_task]:
            if task:
                task.cancel()
        await asyncio.sleep(0.05)

    async def _heartbeat_loop(self) -> None:
        while self.running:
            try:
                await self.write_char(CHAR_MOVE, self.move_payload, response=False)
            except Exception as exc:
                self.logger.log_event("heartbeat-error", str(exc).encode("utf-8", "replace"))
                print(f"\nheartbeat error: {exc}")
                await asyncio.sleep(0.1)
            await asyncio.sleep(self.move_interval_s)

    async def _battery_loop(self) -> None:
        while self.running:
            try:
                data = await self.read_char(CHAR_BATTERY)
                self.last_battery = data
                decoded = f"battery percent?={data[0]}" if data else "empty"
                self.logger.log_event("FED8", data, decoded)
            except Exception as exc:
                self.logger.log_event("FED8-error", str(exc).encode("utf-8", "replace"))
            await asyncio.sleep(4.0)

    def _on_fed5(self, _sender: int, data: bytearray) -> None:
        raw = bytes(data)
        self.last_fed5 = raw
        print(f"\nnotify FED5 {raw.hex()}")
        self.logger.log_event("FED5", raw)

    def _on_fed9(self, _sender: int, data: bytearray) -> None:
        raw = bytes(data)
        if raw:
            self.last_fed9_by_type[raw[0]] = raw
        decoded = decode_fed9(raw)
        print(f"\nnotify FED9 {raw.hex()} | {decoded}")
        self.logger.log_event("FED9", raw, decoded)

    async def run_case(self, case: ProbeCase) -> None:
        print("\n" + "=" * 72)
        print(f"{case.phase}: {case.label}")
        print(f"target={case.target} payload={case.payload.hex()} duration={case.duration_s:.2f}s")
        if case.note:
            print(case.note)
        command = input("ENTER=run | s=skip | q=quit > ").strip().lower()
        if command == "q":
            raise KeyboardInterrupt
        if command == "s":
            self.logger.log_result(case, "SKIP")
            return

        if case.target == "move":
            if not self.client.is_connected:
                raise RuntimeError("BLE client disconnected before movement test")
            self.move_payload = case.payload
            await asyncio.sleep(case.duration_s)
            self.move_payload = b"\x00\x00"
            await asyncio.sleep(0.2)
        elif case.target == "head":
            await self.write_char(CHAR_HEAD, case.payload, response=False)
            await asyncio.sleep(case.duration_s)
        elif case.target == "light":
            await self.write_char(CHAR_LIGHT, case.payload, response=True)
            await asyncio.sleep(case.duration_s)
        elif case.target == "raw-fe00":
            await self.write_char("0000fe00-0000-1000-8000-00805f9b34fb", case.payload, response=True)
            await asyncio.sleep(case.duration_s)
        else:
            raise ValueError(f"unknown target: {case.target}")

        result = input("Що сталося? коротко опиши > ").strip()
        self.logger.log_result(case, result)

    async def capture_sensor_pose(self, phase: str, label: str, seconds: float = 3.0) -> None:
        print("\n" + "=" * 72)
        print(f"{phase}: {label}")
        input("Постав/натисни як описано, потім ENTER для старту запису > ")
        before = dict(self.last_fed9_by_type)
        start = time.time()
        samples: list[tuple[float, int, str, str]] = []
        while time.time() - start < seconds:
            await asyncio.sleep(0.1)
            for packet_type, raw in self.last_fed9_by_type.items():
                if before.get(packet_type) != raw:
                    samples.append((time.time(), packet_type, raw.hex(), decode_fed9(raw)))
                    before[packet_type] = raw
        print("Captured changes:")
        if not samples:
            print("  no FED9 changes observed")
        for _, packet_type, raw_hex, decoded in samples:
            print(f"  type=0x{packet_type:02x} {raw_hex} | {decoded}")
        user_result = input("Твоя нотатка по цьому стану > ").strip()
        case = ProbeCase(phase, label, "sensor", b"", seconds, "sensor capture")
        self.logger.log_result(case, user_result + " | samples=" + json.dumps(samples, ensure_ascii=False))

    async def movement_matrix(self) -> None:
        values = [16, 32, 50, 70, 95, 127]
        cases: list[ProbeCase] = []
        for value in values:
            cases.append(ProbeCase("movement-speed", f"forward speed {value}", "move", bytes([signed_to_byte(value), 0]), 0.55))
        for value in values:
            cases.append(ProbeCase("movement-speed", f"backward speed -{value}", "move", bytes([signed_to_byte(-value), 0]), 0.45))
        for value in values:
            cases.append(ProbeCase("turn-speed", f"spin left turn {value}", "move", bytes([0, signed_to_byte(value)]), 0.45))
            cases.append(ProbeCase("turn-speed", f"spin right turn -{value}", "move", bytes([0, signed_to_byte(-value)]), 0.45))
        combos = [
            (32, 32), (50, 25), (50, 50), (70, 35), (70, 70),
            (95, 40), (95, -40), (70, -70), (-50, 50), (-50, -50),
        ]
        for speed, turn in combos:
            label = f"combined speed {speed} turn {turn}"
            cases.append(ProbeCase("combined-motion", label, "move", bytes([signed_to_byte(speed), signed_to_byte(turn)]), 0.55))
        for case in cases:
            await self.run_case(case)

    async def head_matrix(self) -> None:
        values = [0x00, 0x10, 0x20, 0x30, 0x40, 0x5A, 0x70, 0x90, 0xB0, 0xD0, 0xF0, 0xFF]
        for value in values:
            case = ProbeCase("head-position", f"head raw 0x{value:02x}", "head", bytes([value]), 1.0, "Check: moves up/down? holds? auto-returns?")
            await self.run_case(case)
        print("\nHead hold test: repeated write for 3s.")
        for value in [0x00, 0x30, 0x90, 0xD0, 0xFF]:
            label = f"head hold repeated 0x{value:02x}"
            print("\n" + "=" * 72)
            print(label)
            command = input("ENTER=run | s=skip | q=quit > ").strip().lower()
            if command == "q":
                raise KeyboardInterrupt
            if command == "s":
                self.logger.log_result(ProbeCase("head-hold", label, "head", bytes([value]), 3.0), "SKIP")
                continue
            start = time.time()
            while time.time() - start < 3.0:
                await self.write_char(CHAR_HEAD, bytes([value]), response=False)
                await asyncio.sleep(0.1)
            result = input("Чи тримав градус чи повертався? > ").strip()
            self.logger.log_result(ProbeCase("head-hold", label, "head", bytes([value]), 3.0), result)

    async def light_matrix(self) -> None:
        values = [0x00, 0x01, 0x02, 0x03, 0x05, 0x08, 0x10, 0x20, 0x40, 0x80, 0xC0, 0xFF]
        for value in values:
            case = ProbeCase("light", f"light raw 0x{value:02x}", "light", bytes([value]), 0.8, "Check brightness/color/flicker.")
            await self.run_case(case)

    async def sensor_matrix(self) -> None:
        await self.capture_sensor_pose("cliff", "all wheels/sensors on table/floor")
        await self.capture_sensor_pose("cliff", "front lifted only")
        await self.capture_sensor_pose("cliff", "back lifted only")
        await self.capture_sensor_pose("cliff", "left side lifted only")
        await self.capture_sensor_pose("cliff", "right side lifted only")
        await self.capture_sensor_pose("touch", "left side touch press/release")
        await self.capture_sensor_pose("touch", "right side touch press/release")
        await self.capture_sensor_pose("touch", "front touch press/release")


async def ensure_services(client: BleakClient) -> None:
    for _ in range(12):
        try:
            _ = client.services
            return
        except BleakError:
            await asyncio.sleep(0.5)
    raise RuntimeError("Bluetooth service discovery did not complete")


async def find_device(address: Optional[str]) -> str:
    if address:
        return address
    print(f"Scanning for device containing '{NAME_CONTAINS}'...")
    device = await BleakScanner.find_device_by_filter(
        lambda discovered, _adv: NAME_CONTAINS.lower() in (discovered.name or "").lower(),
        timeout=8.0,
    )
    if not device:
        raise RuntimeError("LOOI not found. Make sure the official app is disconnected.")
    print(f"Found {device.name} at {device.address}")
    return device.address


async def run(args: argparse.Namespace) -> None:
    address = await find_device(args.address)
    run_dir = Path(args.log_dir) / now_stamp()
    logger = ProbeLogger(run_dir)
    logger.summary.update({"address": address, "move_interval_s": args.move_interval})

    stop_event = asyncio.Event()

    def request_stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, request_stop)
        except NotImplementedError:
            pass

    print(f"Connecting to {address}...")
    async with BleakClient(address, timeout=20.0) as client:
        probe = LooiProbe(client, logger, args.move_interval)
        try:
            await probe.init()
            while not stop_event.is_set():
                print("\n" + "=" * 72)
                print("Menu:")
                print("  1 movement speeds/turns/combined")
                print("  2 head positions/hold")
                print("  3 lights")
                print("  4 cliff/touch sensors")
                print("  5 single custom movement")
                print("  q quit")
                choice = input("> ").strip().lower()
                if choice == "q":
                    break
                if choice == "1":
                    await probe.movement_matrix()
                elif choice == "2":
                    await probe.head_matrix()
                elif choice == "3":
                    await probe.light_matrix()
                elif choice == "4":
                    await probe.sensor_matrix()
                elif choice == "5":
                    speed = int(input("speed -127..127 > ").strip())
                    turn = int(input("turn -127..127 > ").strip())
                    duration = float(input("duration seconds, e.g. 0.5 > ").strip() or "0.5")
                    payload = bytes([signed_to_byte(speed), signed_to_byte(turn)])
                    await probe.run_case(ProbeCase("custom-motion", f"custom speed {speed} turn {turn}", "move", payload, duration))
                else:
                    print("Unknown choice")
        finally:
            await probe.shutdown()
            logger.close()
            print(f"\nLogs written to: {run_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive LOOI BLE probe.")
    parser.add_argument("--address", help="BLE address/UUID. If omitted, scan by LOOI name.")
    parser.add_argument("--log-dir", default="looi_probe_runs", help="Directory for CSV/JSON logs.")
    parser.add_argument("--move-interval", type=float, default=0.03, help="Movement heartbeat interval in seconds.")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(run(parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
