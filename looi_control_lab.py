import argparse
import asyncio
import csv
import json
import select
import signal
import sys
import termios
import time
import tty
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

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
UUID_MANUFACTURER = "00002a29-0000-1000-8000-00805f9b34fb"

MOVE_INTERVAL_S = 0.03
DEFAULT_BATTERY_INTERVAL_S = 4.0


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def signed_byte(value: int) -> int:
    return clamp(value, -127, 127) & 0xFF


def int8(value: int) -> int:
    return value - 256 if value >= 128 else value


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def run_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def decode_fed9(data: bytes) -> dict[str, Any]:
    if not data:
        return {"kind": "empty"}
    if data == b"\x11\x01\x00":
        return {"kind": "boot_init_complete"}
    if data == b"\x05":
        return {
            "kind": "phone_dock_state",
            "docked": True,
            "state": "attached",
            "hypothesis": "confirmed by repeated attach/remove test",
        }
    if data == b"\x06":
        return {
            "kind": "phone_dock_state",
            "docked": False,
            "state": "removed",
            "hypothesis": "confirmed by repeated attach/remove test",
        }
    packet_type = data[0]
    if packet_type == 0x01 and len(data) >= 5:
        front_left = data[1]
        front_right = data[2]
        rear_left = data[3]
        rear_right = data[4]
        return {
            "kind": "cliff_contact",
            "front_left": front_left,
            "front_right": front_right,
            "rear_left": rear_left,
            "rear_right": rear_right,
            "bottom_bits": list(data[1:5]),
            "active_low": {
                "front_left": front_left == 0,
                "front_right": front_right == 0,
                "rear_left": rear_left == 0,
                "rear_right": rear_right == 0,
            },
            "hypothesis": "four lower cliff/contact sensors; 0 means over cliff/triggered, 1 means safe/contact",
        }
    if packet_type == 0x02 and len(data) >= 3:
        return {
            "kind": "imu_like",
            "axis_a_i8": int8(data[1]),
            "axis_b_i8": int8(data[2]),
            "int16_be": int.from_bytes(data[1:3], "big", signed=True),
            "int16_le": int.from_bytes(data[1:3], "little", signed=True),
            "hypothesis": "two signed 8-bit IMU/motion axes; isolated tests show one byte changes at a time",
        }
    if packet_type == 0x09 and len(data) >= 2:
        return {
            "kind": "left_side_touch",
            "raw": data[1],
            "pressed": data[1] == 1,
            "hypothesis": "mapped from user test: left side touch sensor",
        }
    if packet_type == 0x0A and len(data) >= 2:
        return {
            "kind": "right_side_touch",
            "raw": data[1],
            "pressed": data[1] == 1,
            "hypothesis": "mapped from user test: right side touch sensor",
        }
    if packet_type == 0x0B and len(data) >= 2:
        return {
            "kind": "external_power_event",
            "raw": data[1],
            "external_power_connected": data[1] == 1,
            "hypothesis": "observed shortly after USB-C cable is plugged into the base",
        }
    if packet_type == 0x0E and len(data) >= 3:
        return {
            "kind": "motion_or_encoder_candidate",
            "value_u16_le": int.from_bytes(data[1:3], "little", signed=False),
            "value_i16_le": int.from_bytes(data[1:3], "little", signed=True),
            "value_u16_be": int.from_bytes(data[1:3], "big", signed=False),
            "value_i16_be": int.from_bytes(data[1:3], "big", signed=True),
            "b1": data[1],
            "b2": data[2],
            "hypothesis": "changes during wheel motion; may be encoder, motor current, or attitude",
        }
    if packet_type == 0x12 and len(data) >= 3:
        return {
            "kind": "front_touch",
            "b1": data[1],
            "b2": data[2],
            "value_u16_le": int.from_bytes(data[1:3], "little", signed=False),
            "hypothesis": "mapped from isolated user test: front center touch sensor",
        }
    return {"kind": "unknown", "type": packet_type, "len": len(data)}


def compact_decode(decoded: dict[str, Any]) -> str:
    kind = decoded.get("kind")
    if kind == "boot_init_complete":
        return "boot/init"
    if kind == "cliff_contact":
        bits = decoded.get("bottom_bits", [None, None, None, None])
        active = decoded.get("active_low", {})
        active_names = [name for name, is_active in active.items() if is_active]
        active_text = ",".join(active_names) if active_names else "none"
        return (
            f"cliff FL={bits[0]} FR={bits[1]} RL={bits[2]} RR={bits[3]} active={active_text}"
        )
    if kind == "imu_like":
        return f"imu8 a={decoded['axis_a_i8']} b={decoded['axis_b_i8']}"
    if kind == "left_side_touch":
        return f"left touch {'press' if decoded['pressed'] else 'release'}"
    if kind == "right_side_touch":
        return f"right touch {'press' if decoded['pressed'] else 'release'}"
    if kind == "phone_dock_state":
        return f"phone {decoded['state']}"
    if kind == "external_power_event":
        return f"usb power event raw={decoded['raw']}"
    if kind == "motion_or_encoder_candidate":
        return f"0e motion? le={decoded['value_i16_le']} b1={decoded['b1']} b2={decoded['b2']}"
    if kind == "front_touch":
        return f"front touch b1={decoded['b1']} b2={decoded['b2']} le={decoded['value_u16_le']}"
    return str(decoded)


class JsonlLogger:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.directory = directory
        self.events_path = directory / "events.jsonl"
        self.keys_path = directory / "keys.csv"
        self.summary_path = directory / "summary.json"
        self.events_file = self.events_path.open("w", encoding="utf-8")
        self.keys_file = self.keys_path.open("w", newline="", encoding="utf-8")
        self.keys = csv.writer(self.keys_file)
        self.keys.writerow(["t", "key", "speed", "turn", "head", "light", "deadman", "note"])
        self.summary: dict[str, Any] = {
            "started_at": now_text(),
            "directory": str(directory),
        }

    def event(self, kind: str, **data: Any) -> None:
        payload = {"t": time.time(), "time": now_text(), "kind": kind, **data}
        self.events_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.events_file.flush()

    def key(self, key: str, state: "ControlState", note: str = "") -> None:
        self.keys.writerow([
            f"{time.time():.3f}",
            key,
            state.speed,
            state.turn,
            state.head,
            state.light,
            int(state.deadman_enabled),
            note,
        ])
        self.keys_file.flush()
        self.event("key", key=key, state=state.as_dict(), note=note)

    def close(self) -> None:
        self.summary["finished_at"] = now_text()
        self.summary_path.write_text(json.dumps(self.summary, indent=2, ensure_ascii=False), encoding="utf-8")
        self.events_file.close()
        self.keys_file.close()


@dataclass
class ControlState:
    speed: int = 0
    turn: int = 0
    speed_step: int = 16
    turn_step: int = 16
    head: int = 0x5A
    head_step: int = 8
    light: int = 0
    light_step: int = 16
    deadman_enabled: bool = True
    deadman_timeout_s: float = 3.0
    last_key_time: float = 0.0

    def move_payload(self) -> bytes:
        return bytes([signed_byte(self.speed), signed_byte(self.turn)])

    def stop_motion(self) -> None:
        self.speed = 0
        self.turn = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "speed": self.speed,
            "turn": self.turn,
            "speed_step": self.speed_step,
            "turn_step": self.turn_step,
            "head": self.head,
            "head_step": self.head_step,
            "light": self.light,
            "light_step": self.light_step,
            "deadman_enabled": self.deadman_enabled,
            "deadman_timeout_s": self.deadman_timeout_s,
        }


class TerminalMode:
    def __init__(self):
        self.old_settings: Optional[list[Any]] = None

    def __enter__(self) -> "TerminalMode":
        self.old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.restore(final=True)

    def restore(self, final: bool = False) -> None:
        if self.old_settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
            if final:
                self.old_settings = None

    def raw(self) -> None:
        if self.old_settings is not None:
            tty.setcbreak(sys.stdin.fileno())


def key_available() -> bool:
    return select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], [])


def read_key() -> str:
    first = sys.stdin.read(1)
    if first == "\x1b" and key_available():
        second = sys.stdin.read(1)
        third = sys.stdin.read(1) if key_available() else ""
        return first + second + third
    return first


class LooiClient:
    def __init__(self, client: BleakClient, logger: JsonlLogger, battery_interval_s: float, quiet_ble: bool = False):
        self.client = client
        self.logger = logger
        self.battery_interval_s = battery_interval_s
        self.quiet_ble = quiet_ble
        self.chars: dict[str, Any] = {}
        self.running = True
        self.last_fed5: Optional[bytes] = None
        self.last_fed9: Optional[bytes] = None
        self.last_fed9_decoded: Optional[dict[str, Any]] = None
        self.last_battery: Optional[bytes] = None
        self.heartbeat_errors = 0
        self.heartbeat_writes = 0
        self._last_move_payload: Optional[bytes] = None

    async def init(self) -> None:
        try:
            manufacturer = bytes(await self.client.read_gatt_char(UUID_MANUFACTURER))
            self.logger.event("read", char="2A29", hex=manufacturer.hex(), ascii=manufacturer.decode("ascii", "replace"))
            if not self.quiet_ble:
                print(f"2A29 manufacturer: {manufacturer!r}")
        except Exception as exc:
            self.logger.event("warning", step="read_2a29", error=str(exc))
            if not self.quiet_ble:
                print(f"2A29 read skipped: {exc}")

        await self.ensure_services()
        self.resolve_chars()

        if not self.quiet_ble:
            print("Handshake: FEDA <- 01")
        await self.write(CHAR_FEDA, b"\x01", response=True)
        await asyncio.sleep(0.1)

        if not self.quiet_ble:
            print("Subscribing: FED5 sensors, FED9 telemetry")
        await self.client.start_notify(self.char(CHAR_SENS), self.on_fed5)
        await self.client.start_notify(self.char(CHAR_STREAM), self.on_fed9)
        await asyncio.sleep(0.3)

        if not self.quiet_ble:
            print("Handshake: FEDA <- 03")
        await self.write(CHAR_FEDA, b"\x03", response=True)
        await asyncio.sleep(0.2)

        await self.write(CHAR_MOVE, b"\x00\x00", response=False)
        battery = await self.read(CHAR_BATTERY)
        self.last_battery = battery
        self.logger.event(
            "health",
            connected=self.client.is_connected,
            battery_hex=battery.hex(),
            battery_percent_guess=battery[0] if battery else None,
            battery_status_guess=battery[1] if len(battery) > 1 else None,
        )
        if not self.quiet_ble:
            print(f"Health OK: connected={self.client.is_connected}, FED8 battery={battery.hex()}")

    async def ensure_services(self) -> None:
        for attempt in range(12):
            try:
                _ = self.client.services
                return
            except BleakError:
                await asyncio.sleep(0.5)
                self.logger.event("service_discovery_wait", attempt=attempt + 1)
        raise RuntimeError("Bluetooth service discovery did not complete")

    def resolve_chars(self) -> None:
        required = [CHAR_MOVE, CHAR_HEAD, CHAR_LIGHT, CHAR_SENS, CHAR_BATTERY, CHAR_STREAM, CHAR_FEDA]
        missing = []
        for uuid in required:
            characteristic = self.client.services.get_characteristic(uuid)
            if characteristic is None:
                missing.append(uuid)
            else:
                self.chars[uuid] = characteristic
        if missing:
            raise RuntimeError("Missing characteristics: " + ", ".join(missing))
        self.logger.event("characteristics_resolved", count=len(self.chars))

    def char(self, uuid: str) -> Any:
        characteristic = self.chars.get(uuid)
        if characteristic is None:
            raise RuntimeError(f"Characteristic is not resolved: {uuid}")
        return characteristic

    async def write(self, uuid: str, payload: bytes, response: bool) -> None:
        if not self.client.is_connected:
            raise RuntimeError("BLE client is disconnected")
        await self.client.write_gatt_char(self.char(uuid), payload, response=response)

    async def read(self, uuid: str) -> bytes:
        if not self.client.is_connected:
            raise RuntimeError("BLE client is disconnected")
        return bytes(await self.client.read_gatt_char(self.char(uuid)))

    def on_fed5(self, _sender: int, data: bytearray) -> None:
        raw = bytes(data)
        self.last_fed5 = raw
        self.logger.event("notify", char="FED5", hex=raw.hex())
        if not self.quiet_ble:
            print(f"\nFED5 notify: {raw.hex()}")

    def on_fed9(self, _sender: int, data: bytearray) -> None:
        raw = bytes(data)
        decoded = decode_fed9(raw)
        self.last_fed9 = raw
        self.last_fed9_decoded = decoded
        self.logger.event("notify", char="FED9", hex=raw.hex(), decoded=decoded)
        if not self.quiet_ble:
            print(f"\nFED9 notify: {raw.hex()} | {compact_decode(decoded)}")

    async def movement_loop(self, state: ControlState) -> None:
        while self.running:
            try:
                payload = state.move_payload()
                await self.write(CHAR_MOVE, payload, response=False)
                self.heartbeat_writes += 1
                if payload != self._last_move_payload:
                    self._last_move_payload = payload
                    self.logger.event("move_state", payload_hex=payload.hex(), speed=state.speed, turn=state.turn)
            except Exception as exc:
                self.heartbeat_errors += 1
                self.logger.event("heartbeat_error", error=str(exc), connected=self.client.is_connected)
                if not self.quiet_ble:
                    print(f"\nHEARTBEAT ERROR: {exc}")
                await asyncio.sleep(0.2)
            await asyncio.sleep(MOVE_INTERVAL_S)

    async def battery_loop(self) -> None:
        while self.running:
            try:
                data = await self.read(CHAR_BATTERY)
                self.last_battery = data
                percent = data[0] if data else None
                status = data[1] if len(data) > 1 else None
                self.logger.event("battery", hex=data.hex(), percent_guess=percent, status_guess=status)
            except Exception as exc:
                self.logger.event("battery_error", error=str(exc), connected=self.client.is_connected)
                if not self.quiet_ble:
                    print(f"\nBATTERY ERROR: {exc}")
            await asyncio.sleep(self.battery_interval_s)

    async def set_head(self, value: int) -> None:
        value = clamp(value, 0, 255)
        await self.write(CHAR_HEAD, bytes([value]), response=False)
        self.logger.event("head_write", value=value, hex=f"{value:02x}")

    async def set_light(self, value: int) -> None:
        value = clamp(value, 0, 255)
        await self.write(CHAR_LIGHT, bytes([value]), response=True)
        self.logger.event("light_write", value=value, hex=f"{value:02x}")

    async def shutdown(self) -> None:
        self.running = False
        try:
            await self.write(CHAR_MOVE, b"\x00\x00", response=False)
            await self.write(CHAR_LIGHT, b"\x00", response=True)
        except Exception as exc:
            self.logger.event("shutdown_warning", error=str(exc))


def print_help() -> None:
    print(
        """
LOOI CONTROL LAB

Рух, latched mode:
  w/s        speed +step / -step
  a/d        turn left +step / right -step
  z          speed = 0
  c          turn = 0
  SPACE      emergency STOP speed+turn
  1..5       set step: 8 / 16 / 32 / 64 / 127
  p          short forward pulse using current step
  y          short spin-left pulse using current step
  t          toggle deadman auto-stop after 3s without keys

Голова:
  i/k        head up/down by step
  u          head raw 0x00 look up
  o          head center 0x5A
  l          head raw 0xFF down/nod
  [ / ]      head step -/+

Фара:
  f          toggle off/max
  v/b        light brightness -/+ step
  g          quick blink

Сенсори/лог:
  e          print last FED5/FED9/battery
  n          add text note to logs
  h/?        show this help
  q          stop and quit
"""
    )


def status_line(state: ControlState, looi: LooiClient) -> str:
    if looi.last_battery:
        battery_status = looi.last_battery[1] if len(looi.last_battery) > 1 else None
        power = "usb" if battery_status == 1 else "battery" if battery_status == 0 else "?"
        battery = f"{looi.last_battery.hex()}({power})"
    else:
        battery = "-"
    fed9 = compact_decode(looi.last_fed9_decoded) if looi.last_fed9_decoded else "-"
    return (
        f"speed={state.speed:4d} turn={state.turn:4d} "
        f"head=0x{state.head:02X} light=0x{state.light:02X} "
        f"step={state.speed_step} deadman={'on' if state.deadman_enabled else 'off'} "
        f"connected={looi.client.is_connected} batt={battery} fed9={fed9} "
        f"hb={looi.heartbeat_writes}/{looi.heartbeat_errors}"
    )


async def prompt_note(term: TerminalMode, logger: JsonlLogger, state: ControlState) -> None:
    term.restore()
    try:
        note = input("\nNote for log > ").strip()
        logger.key("NOTE", state, note=note)
    finally:
        term.raw()


async def run_dock_test(looi: LooiClient, logger: JsonlLogger, state: ControlState) -> None:
    print(
        """
LOOI PHONE MOUNT / DOCK TEST

Нічого не керуємо, рух завжди STOP.
Ти фізично кріпиш/знімаєш телефон, вставляєш/дістаєш кабель живлення бази.

Клавіші-маркери для логу:
  a   marker: зараз кріплю телефон
  r   marker: зараз знімаю телефон
  c   marker: зараз вставляю USB-C кабель у базу
  x   marker: зараз дістаю USB-C кабель з бази
  e   print last FED5/FED9/battery
  n   текстова нотатка
  q   завершити тест
"""
    )
    state.stop_motion()
    movement_task = asyncio.create_task(looi.movement_loop(state))
    battery_task = asyncio.create_task(looi.battery_loop())
    logger.event("dock_test_start")
    last_status = 0.0
    try:
        with TerminalMode() as term:
            while True:
                if key_available():
                    key = read_key().lower()
                    state.last_key_time = time.time()
                    if key == "q":
                        logger.key("dock:q", state, "quit dock test")
                        break
                    if key == "a":
                        logger.key("dock:attach_marker", state, "USER_MARKER attaching phone now")
                        print("\nMARKER logged: attaching phone now")
                    elif key == "r":
                        logger.key("dock:remove_marker", state, "USER_MARKER removing phone now")
                        print("\nMARKER logged: removing phone now")
                    elif key == "c":
                        logger.key("dock:cable_in_marker", state, "USER_MARKER plugging USB-C cable into base now")
                        print("\nMARKER logged: plugging USB-C cable into base now")
                    elif key == "x":
                        logger.key("dock:cable_out_marker", state, "USER_MARKER unplugging USB-C cable from base now")
                        print("\nMARKER logged: unplugging USB-C cable from base now")
                    elif key == "e":
                        print("\nLast sensor state:")
                        print(f"  FED5: {looi.last_fed5.hex() if looi.last_fed5 else '-'}")
                        print(f"  FED9: {looi.last_fed9.hex() if looi.last_fed9 else '-'}")
                        print(f"  FED9 decoded: {looi.last_fed9_decoded if looi.last_fed9_decoded else '-'}")
                        print(f"  FED8 battery: {looi.last_battery.hex() if looi.last_battery else '-'}")
                        logger.key("dock:print_state", state, "printed sensor state")
                    elif key == "n":
                        await prompt_note(term, logger, state)
                    elif key in {"h", "?"}:
                        print("Dock test keys: a=attach, r=remove, c=cable in, x=cable out, e=state, n=note, q=quit")
                    else:
                        logger.key(f"dock:ignored:{repr(key)}", state)

                if time.time() - last_status > 0.5:
                    last_status = time.time()
                    print("\r" + status_line(state, looi)[:220], end="", flush=True)

                await asyncio.sleep(0.01)
    finally:
        logger.event("dock_test_end")
        movement_task.cancel()
        battery_task.cancel()


SENSOR_TEST_STEPS = [
    (
        "bottom_front_left",
        "Нижній ПЕРЕДНІЙ ЛІВИЙ: наведи над обривом / закрий тільки його. 3 рази.",
    ),
    (
        "bottom_rear_left",
        "Нижній ЗАДНІЙ ЛІВИЙ: наведи над обривом / закрий тільки його. 3 рази.",
    ),
    (
        "bottom_front_right",
        "Нижній ПЕРЕДНІЙ ПРАВИЙ: наведи над обривом / закрий тільки його. 3 рази.",
    ),
    (
        "bottom_rear_right",
        "Нижній ЗАДНІЙ ПРАВИЙ: наведи над обривом / закрий тільки його. 3 рази.",
    ),
    (
        "touch_left_side",
        "ЛІВИЙ БОКОВИЙ touch: торкнись/відпусти 3 рази.",
    ),
    (
        "touch_right_side",
        "ПРАВИЙ БОКОВИЙ touch: торкнись/відпусти 3 рази.",
    ),
    (
        "touch_front_center",
        "ПЕРЕДНІЙ ЦЕНТРАЛЬНИЙ touch: торкнись/відпусти 3 рази.",
    ),
]


PHYSICS_TEST_STEPS = [
    (
        "idle_still",
        "Постав базу рівно. Не торкайся 5 секунд.",
        "none",
    ),
    (
        "tilt_forward",
        "Нахили корпус вперед/носом вниз 3 рази і поверни рівно.",
        "none",
    ),
    (
        "tilt_backward",
        "Нахили корпус назад 3 рази і поверни рівно.",
        "none",
    ),
    (
        "tilt_left",
        "Нахили корпус ліворуч 3 рази і поверни рівно.",
        "none",
    ),
    (
        "tilt_right",
        "Нахили корпус праворуч 3 рази і поверни рівно.",
        "none",
    ),
    (
        "yaw_rotate",
        "Поверни корпус руками навколо вертикальної осі ліворуч/праворуч 3 рази.",
        "none",
    ),
    (
        "head_up_cmd",
        "Я дам команду голові raw 0x00. Дивись фізично, чи йде вгору/тримає позицію.",
        "head_up",
    ),
    (
        "head_center_cmd",
        "Я дам команду голові center 0x5A. Дивись, чи повертається в центр.",
        "head_center",
    ),
    (
        "head_down_cmd",
        "Я дам команду голові raw 0xFF. Дивись, чи йде вниз/тримає позицію.",
        "head_down",
    ),
    (
        "tracks_free_forward",
        "Підніми базу так, щоб гусениці/колеса були в повітрі. Я дам малий forward.",
        "move_forward",
    ),
    (
        "tracks_resistance_forward",
        "Обережно дай легкий опір гусеницям/колесам при малому forward. Не блокуйте жорстко.",
        "move_forward",
    ),
    (
        "tracks_free_turn",
        "Підніми базу. Я дам малий поворот на місці.",
        "turn_left",
    ),
    (
        "tracks_resistance_turn",
        "Обережно дай легкий опір при малому повороті. Не блокуйте жорстко.",
        "turn_left",
    ),
]


PASSIVE_TEST_STEPS = [
    (
        "idle_passive_baseline",
        "Постав базу рівно. Не торкайся 5 секунд.",
    ),
    (
        "manual_head_bend_up_down",
        "Рукою дуже обережно нахили голову вгору/вниз 3 рази. Без сили.",
    ),
    (
        "manual_head_hold_offset",
        "Обережно відведи голову в одну позицію і потримай 3-5 секунд, потім відпусти.",
    ),
    (
        "manual_left_track_spin",
        "Підніми базу і прокрути ЛІВУ гусеницю/колесо рукою вперед/назад 3 рази.",
    ),
    (
        "manual_right_track_spin",
        "Підніми базу і прокрути ПРАВУ гусеницю/колесо рукою вперед/назад 3 рази.",
    ),
    (
        "body_light_taps",
        "Легко постукай пальцем по корпусу 3 рази. Не сильно.",
    ),
    (
        "head_light_taps",
        "Легко постукай пальцем по голові/кріпленню 3 рази. Не сильно.",
    ),
    (
        "quick_body_shake",
        "Обережно швидко похитай корпус 2-3 секунди.",
    ),
]


FED9_MOTION_TEST_STEPS = [
    (
        "flat_table_idle",
        "Постав базу рівно на стіл/підлогу. Не торкайся 10 секунд.",
    ),
    (
        "flat_table_light_touch",
        "Ледь притримай корпус зверху, не нахиляй. Перевіряємо, чи сам дотик дає 02/0e.",
    ),
    (
        "pitch_nose_down_hold",
        "Нахили НІС ВНИЗ приблизно 15-30°, потримай стабільно 5 секунд, поверни рівно.",
    ),
    (
        "pitch_nose_up_hold",
        "Нахили НІС ВГОРУ приблизно 15-30°, потримай стабільно 5 секунд, поверни рівно.",
    ),
    (
        "roll_left_hold",
        "Нахили корпус ЛІВОРУЧ приблизно 15-30°, потримай стабільно 5 секунд, поверни рівно.",
    ),
    (
        "roll_right_hold",
        "Нахили корпус ПРАВОРУЧ приблизно 15-30°, потримай стабільно 5 секунд, поверни рівно.",
    ),
    (
        "yaw_left_on_table",
        "Не нахиляй. Повільно поверни корпус на столі ЛІВОРУЧ навколо вертикальної осі 2-3 рази.",
    ),
    (
        "yaw_right_on_table",
        "Не нахиляй. Повільно поверни корпус на столі ПРАВОРУЧ навколо вертикальної осі 2-3 рази.",
    ),
    (
        "slide_forward_back",
        "Не крути гусениці рукою. Акуратно посунь весь корпус вперед-назад по столу 2-3 рази.",
    ),
    (
        "left_track_fixed_body",
        "Корпус тримай максимально нерухомо/рівно. Прокрути тільки ЛІВУ гусеницю 2-3 рази.",
    ),
    (
        "right_track_fixed_body",
        "Корпус тримай максимально нерухомо/рівно. Прокрути тільки ПРАВУ гусеницю 2-3 рази.",
    ),
]


FED9_ANGLE_TEST_STEPS = [
    (
        "flat_idle_reference",
        "Постав рівно. Ніс робота дивиться вперед на умовну мітку. Не торкайся 8 секунд.",
    ),
    (
        "yaw_left_90_flat",
        "На столі, без нахилу: поверни корпус ЛІВОРУЧ на 90° і потримай. НЕ повертай назад у цьому кроці.",
    ),
    (
        "yaw_right_90_flat",
        "З поточної позиції поверни корпус ПРАВОРУЧ на 90° і потримай. Це має повернути приблизно до старту.",
    ),
    (
        "yaw_left_180_flat",
        "На столі, без нахилу: поверни корпус ЛІВОРУЧ на 180° і потримай. НЕ повертай назад у цьому кроці.",
    ),
    (
        "yaw_right_180_flat",
        "З поточної позиції поверни корпус ПРАВОРУЧ на 180° і потримай. Це має повернути приблизно до старту.",
    ),
    (
        "pitch_nose_down_45",
        "Ніс ВНИЗ приблизно 45°: підніми зад або постав на книгу, потримай 5 секунд.",
    ),
    (
        "pitch_nose_up_45",
        "Ніс ВГОРУ приблизно 45°: підніми перед або постав на книгу, потримай 5 секунд.",
    ),
    (
        "roll_left_45",
        "Нахил ЛІВОРУЧ приблизно 45°: підніми правий бік, потримай 5 секунд.",
    ),
    (
        "roll_right_45",
        "Нахил ПРАВОРУЧ приблизно 45°: підніми лівий бік, потримай 5 секунд.",
    ),
    (
        "nose_down_90_vertical",
        "90°: постав/потримай робота майже вертикально НОСОМ ВНИЗ 5 секунд.",
    ),
    (
        "nose_up_90_vertical",
        "90°: постав/потримай робота майже вертикально НОСОМ ВГОРУ 5 секунд.",
    ),
    (
        "left_side_90",
        "90°: поклади/потримай робота на ЛІВОМУ боці 5 секунд.",
    ),
    (
        "right_side_90",
        "90°: поклади/потримай робота на ПРАВОМУ боці 5 секунд.",
    ),
    (
        "flat_after_all",
        "Поверни рівно на стіл. Не торкайся 8 секунд.",
    ),
]


def print_last_sensor_state(looi: LooiClient) -> None:
    print("\nLast sensor state:")
    print(f"  FED5: {looi.last_fed5.hex() if looi.last_fed5 else '-'}")
    print(f"  FED9: {looi.last_fed9.hex() if looi.last_fed9 else '-'}")
    print(f"  FED9 decoded: {looi.last_fed9_decoded if looi.last_fed9_decoded else '-'}")
    print(f"  FED8 battery: {looi.last_battery.hex() if looi.last_battery else '-'}")


async def run_sensor_test(looi: LooiClient, logger: JsonlLogger, state: ControlState) -> None:
    print(
        """
LOOI FULL SENSOR MAPPING TEST

Рух вимкнений: база постійно отримує STOP.
Для кожного кроку:
  ENTER  почати крок
  зроби дію 3 рази
  ENTER  завершити крок і перейти далі
  e      print last state
  n      текстова нотатка
  q      завершити тест

BLE-події пишуться у файл. У терміналі тільки кроки.
"""
    )
    state.stop_motion()
    movement_task = asyncio.create_task(looi.movement_loop(state))
    battery_task = asyncio.create_task(looi.battery_loop())
    logger.event("sensor_test_start", steps=[step_id for step_id, _ in SENSOR_TEST_STEPS])
    last_status = 0.0
    try:
        with TerminalMode() as term:
            for index, (step_id, instruction) in enumerate(SENSOR_TEST_STEPS, start=1):
                print(f"\n\nSTEP {index}/{len(SENSOR_TEST_STEPS)}: {step_id}")
                print(instruction)
                print("ENTER = start. Потім зроби 3 рази. ENTER = next. q = stop.")

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("sensor:q", state, "quit sensor test before step")
                            return
                        if key in {"\n", "\r"}:
                            logger.key(f"sensor:start:{step_id}", state, instruction)
                            print(f"\nSTART: {step_id}. Роби дію 3 рази, потім ENTER.")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("sensor:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("sensor:q", state, "quit sensor test during step")
                            return
                        if key in {"\n", "\r"}:
                            logger.key(f"sensor:end:{step_id}", state, "finished sensor step")
                            print(f"\nEND: {step_id}")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("sensor:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)
            logger.key("sensor:complete", state, "all sensor test steps completed")
            print("\nSensor test complete.")
    finally:
        logger.event("sensor_test_end")
        movement_task.cancel()
        battery_task.cancel()


async def apply_physics_action(action: str, state: ControlState, looi: LooiClient, logger: JsonlLogger) -> None:
    state.stop_motion()
    if action == "head_up":
        state.head = 0x00
        await looi.set_head(state.head)
    elif action == "head_center":
        state.head = 0x5A
        await looi.set_head(state.head)
    elif action == "head_down":
        state.head = 0xFF
        await looi.set_head(state.head)
    elif action == "move_forward":
        state.speed = 24
        state.turn = 0
    elif action == "turn_left":
        state.speed = 0
        state.turn = 24
    logger.event("physics_action_applied", action=action, state=state.as_dict())


async def run_physics_test(looi: LooiClient, logger: JsonlLogger, state: ControlState) -> None:
    print(
        """
LOOI PHYSICS / IMU / MOTOR FEEDBACK TEST

Рух вимкнений, крім кроків з гусеницями. Там швидкість мала: 24/127.
Для кожного кроку:
  ENTER  почати крок
  зроби дію 3 рази або почекай 5 секунд
  ENTER  завершити крок і перейти далі
  e      print last state
  n      текстова нотатка
  q      завершити тест

BLE-події пишуться у файл. У терміналі тільки кроки.
"""
    )
    state.stop_motion()
    movement_task = asyncio.create_task(looi.movement_loop(state))
    battery_task = asyncio.create_task(looi.battery_loop())
    logger.event("physics_test_start", steps=[step_id for step_id, _, _ in PHYSICS_TEST_STEPS])
    last_status = 0.0
    try:
        with TerminalMode() as term:
            for index, (step_id, instruction, action) in enumerate(PHYSICS_TEST_STEPS, start=1):
                state.stop_motion()
                print(f"\n\nSTEP {index}/{len(PHYSICS_TEST_STEPS)}: {step_id}")
                print(instruction)
                print("ENTER = start. ENTER = next. q = stop.")

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("physics:q", state, "quit physics test before step")
                            return
                        if key in {"\n", "\r"}:
                            logger.key(f"physics:start:{step_id}", state, instruction)
                            await apply_physics_action(action, state, looi, logger)
                            print(f"\nSTART: {step_id}. Виконай дію, потім ENTER.")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("physics:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("physics:q", state, "quit physics test during step")
                            return
                        if key in {"\n", "\r"}:
                            state.stop_motion()
                            logger.key(f"physics:end:{step_id}", state, "finished physics step")
                            print(f"\nEND: {step_id}")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("physics:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)
            state.stop_motion()
            state.head = 0x5A
            await looi.set_head(state.head)
            logger.key("physics:complete", state, "all physics test steps completed")
            print("\nPhysics test complete.")
    finally:
        state.stop_motion()
        logger.event("physics_test_end")
        movement_task.cancel()
        battery_task.cancel()


async def run_passive_test(looi: LooiClient, logger: JsonlLogger, state: ControlState) -> None:
    print(
        """
LOOI PASSIVE FEEDBACK TEST

Рух повністю вимкнений: тільки STOP heartbeat.
Тестуємо, чи база відчуває ручне згинання голови, ручне кручення гусениць, легкі удари/струси.
Для кожного кроку:
  ENTER  почати крок
  зроби дію 3 рази або почекай 5 секунд
  ENTER  завершити крок і перейти далі
  e      print last state
  n      текстова нотатка
  q      завершити тест

BLE-події пишуться у файл. У терміналі тільки кроки.
"""
    )
    state.stop_motion()
    movement_task = asyncio.create_task(looi.movement_loop(state))
    battery_task = asyncio.create_task(looi.battery_loop())
    logger.event("passive_test_start", steps=[step_id for step_id, _ in PASSIVE_TEST_STEPS])
    last_status = 0.0
    try:
        with TerminalMode() as term:
            for index, (step_id, instruction) in enumerate(PASSIVE_TEST_STEPS, start=1):
                state.stop_motion()
                print(f"\n\nSTEP {index}/{len(PASSIVE_TEST_STEPS)}: {step_id}")
                print(instruction)
                print("ENTER = start. ENTER = next. q = stop.")

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("passive:q", state, "quit passive test before step")
                            return
                        if key in {"\n", "\r"}:
                            logger.key(f"passive:start:{step_id}", state, instruction)
                            print(f"\nSTART: {step_id}. Виконай дію, потім ENTER.")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("passive:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("passive:q", state, "quit passive test during step")
                            return
                        if key in {"\n", "\r"}:
                            state.stop_motion()
                            logger.key(f"passive:end:{step_id}", state, "finished passive step")
                            print(f"\nEND: {step_id}")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("passive:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)
            logger.key("passive:complete", state, "all passive test steps completed")
            print("\nPassive test complete.")
    finally:
        state.stop_motion()
        logger.event("passive_test_end")
        movement_task.cancel()
        battery_task.cancel()


async def run_fed9_motion_test(looi: LooiClient, logger: JsonlLogger, state: ControlState) -> None:
    print(
        """
LOOI FED9 02/0E ISOLATION TEST

Рух повністю вимкнений: тільки STOP heartbeat.
Ціль: відокремити FED9 type 02 і type 0e від нижніх/touch сенсорів.

Для кожного кроку:
  ENTER  почати крок
  зроби тільки описану дію
  ENTER  завершити крок і перейти далі
  e      print last state
  n      текстова нотатка
  q      завершити тест

Важливо: не торкайся бокових/переднього touch, якщо це не треба; нижні сенсори не закривай пальцями.
BLE-події пишуться у файл. У терміналі тільки кроки.
"""
    )
    state.stop_motion()
    movement_task = asyncio.create_task(looi.movement_loop(state))
    battery_task = asyncio.create_task(looi.battery_loop())
    logger.event("fed9motion_test_start", steps=[step_id for step_id, _ in FED9_MOTION_TEST_STEPS])
    last_status = 0.0
    try:
        with TerminalMode() as term:
            for index, (step_id, instruction) in enumerate(FED9_MOTION_TEST_STEPS, start=1):
                state.stop_motion()
                print(f"\n\nSTEP {index}/{len(FED9_MOTION_TEST_STEPS)}: {step_id}")
                print(instruction)
                print("ENTER = start. ENTER = next. q = stop.")

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("fed9motion:q", state, "quit fed9 motion test before step")
                            return
                        if key in {"\n", "\r"}:
                            logger.key(f"fed9motion:start:{step_id}", state, instruction)
                            print(f"\nSTART: {step_id}. Виконай дію, потім ENTER.")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("fed9motion:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("fed9motion:q", state, "quit fed9 motion test during step")
                            return
                        if key in {"\n", "\r"}:
                            state.stop_motion()
                            logger.key(f"fed9motion:end:{step_id}", state, "finished fed9 motion step")
                            print(f"\nEND: {step_id}")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("fed9motion:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)
            logger.key("fed9motion:complete", state, "all fed9 motion test steps completed")
            print("\nFED9 motion test complete.")
    finally:
        state.stop_motion()
        logger.event("fed9motion_test_end")
        movement_task.cancel()
        battery_task.cancel()


async def run_fed9_angle_test(looi: LooiClient, logger: JsonlLogger, state: ControlState) -> None:
    print(
        """
LOOI FED9 02/0E ANGLE TEST

Рух повністю вимкнений: тільки STOP heartbeat.
Тут не треба міряти 15-30°. Використовуємо прості позиції: 45°, 90°, 180°.

Для кожного кроку:
  ENTER  почати крок
  зроби тільки описану дію і потримай позицію
  ENTER  завершити крок і перейти далі
  e      print last state
  n      текстова нотатка
  q      завершити тест

Порада: для 45° можна підкласти книгу/коробку під один край. Для 90° просто поклади/постав на бік.
Нижні сенсори можуть спрацьовувати в 90° позиціях — це нормально, аналізатор їх відфільтрує.
"""
    )
    state.stop_motion()
    movement_task = asyncio.create_task(looi.movement_loop(state))
    battery_task = asyncio.create_task(looi.battery_loop())
    logger.event("fed9angle_test_start", steps=[step_id for step_id, _ in FED9_ANGLE_TEST_STEPS])
    last_status = 0.0
    try:
        with TerminalMode() as term:
            for index, (step_id, instruction) in enumerate(FED9_ANGLE_TEST_STEPS, start=1):
                state.stop_motion()
                print(f"\n\nSTEP {index}/{len(FED9_ANGLE_TEST_STEPS)}: {step_id}")
                print(instruction)
                print("ENTER = start. ENTER = next. q = stop.")

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("fed9angle:q", state, "quit fed9 angle test before step")
                            return
                        if key in {"\n", "\r"}:
                            logger.key(f"fed9angle:start:{step_id}", state, instruction)
                            print(f"\nSTART: {step_id}. Виконай дію, потримай, потім ENTER.")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("fed9angle:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)

                while True:
                    if key_available():
                        key = read_key().lower()
                        state.last_key_time = time.time()
                        if key == "q":
                            logger.key("fed9angle:q", state, "quit fed9 angle test during step")
                            return
                        if key in {"\n", "\r"}:
                            state.stop_motion()
                            logger.key(f"fed9angle:end:{step_id}", state, "finished fed9 angle step")
                            print(f"\nEND: {step_id}")
                            break
                        if key == "e":
                            print_last_sensor_state(looi)
                            logger.key("fed9angle:print_state", state, "printed sensor state")
                        elif key == "n":
                            await prompt_note(term, logger, state)

                    if not looi.quiet_ble and time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)
                    await asyncio.sleep(0.01)
            logger.key("fed9angle:complete", state, "all fed9 angle test steps completed")
            print("\nFED9 angle test complete.")
    finally:
        state.stop_motion()
        logger.event("fed9angle_test_end")
        movement_task.cancel()
        battery_task.cancel()


async def handle_key(key: str, state: ControlState, looi: LooiClient, logger: JsonlLogger, term: TerminalMode) -> bool:
    normalized = key.lower()
    state.last_key_time = time.time()
    note = ""

    if normalized == "q":
        logger.key("q", state, "quit")
        return False
    if key == " ":
        state.stop_motion()
        note = "emergency stop"
    elif normalized == "w":
        state.speed = clamp(state.speed + state.speed_step, -127, 127)
    elif normalized == "s":
        state.speed = clamp(state.speed - state.speed_step, -127, 127)
    elif normalized == "a":
        state.turn = clamp(state.turn + state.turn_step, -127, 127)
    elif normalized == "d":
        state.turn = clamp(state.turn - state.turn_step, -127, 127)
    elif normalized == "z":
        state.speed = 0
    elif normalized == "c":
        state.turn = 0
    elif normalized in {"1", "2", "3", "4", "5"}:
        step = {"1": 8, "2": 16, "3": 32, "4": 64, "5": 127}[normalized]
        state.speed_step = step
        state.turn_step = step
        note = f"step={step}"
    elif normalized == "p":
        old_speed, old_turn = state.speed, state.turn
        state.speed, state.turn = state.speed_step, 0
        logger.key("p:start", state, "forward pulse")
        await asyncio.sleep(0.6)
        state.speed, state.turn = old_speed, old_turn
        note = "forward pulse done"
    elif normalized == "y":
        old_speed, old_turn = state.speed, state.turn
        state.speed, state.turn = 0, state.turn_step
        logger.key("y:start", state, "spin pulse")
        await asyncio.sleep(0.5)
        state.speed, state.turn = old_speed, old_turn
        note = "spin pulse done"
    elif normalized == "t":
        state.deadman_enabled = not state.deadman_enabled
        note = f"deadman={state.deadman_enabled}"
    elif normalized == "i":
        state.head = clamp(state.head - state.head_step, 0, 255)
        await looi.set_head(state.head)
    elif normalized == "k":
        state.head = clamp(state.head + state.head_step, 0, 255)
        await looi.set_head(state.head)
    elif normalized == "u":
        state.head = 0x00
        await looi.set_head(state.head)
    elif normalized == "o":
        state.head = 0x5A
        await looi.set_head(state.head)
    elif normalized == "l":
        state.head = 0xFF
        await looi.set_head(state.head)
    elif normalized == "[":
        state.head_step = clamp(state.head_step - 1, 1, 64)
        note = f"head_step={state.head_step}"
    elif normalized == "]":
        state.head_step = clamp(state.head_step + 1, 1, 64)
        note = f"head_step={state.head_step}"
    elif normalized == "f":
        state.light = 0xFF if state.light == 0 else 0
        await looi.set_light(state.light)
    elif normalized == "v":
        state.light = clamp(state.light - state.light_step, 0, 255)
        await looi.set_light(state.light)
    elif normalized == "b":
        state.light = clamp(state.light + state.light_step, 0, 255)
        await looi.set_light(state.light)
    elif normalized == "g":
        old = state.light
        for value in [0xFF, 0x00, 0xFF, 0x00, old]:
            await looi.set_light(value)
            await asyncio.sleep(0.15)
        state.light = old
        note = "blink"
    elif normalized == "e":
        print("\nLast sensor state:")
        print(f"  FED5: {looi.last_fed5.hex() if looi.last_fed5 else '-'}")
        print(f"  FED9: {looi.last_fed9.hex() if looi.last_fed9 else '-'}")
        print(f"  FED9 decoded: {looi.last_fed9_decoded if looi.last_fed9_decoded else '-'}")
        print(f"  FED8 battery: {looi.last_battery.hex() if looi.last_battery else '-'}")
        note = "printed sensors"
    elif normalized == "n":
        await prompt_note(term, logger, state)
        return True
    elif normalized in {"h", "?"}:
        print_help()
        note = "help"
    else:
        note = f"ignored={repr(key)}"

    logger.key(key, state, note)
    return True


async def find_device(address: Optional[str]) -> str:
    if address:
        return address
    print(f"Scanning for '{NAME_CONTAINS}'...")
    device = await BleakScanner.find_device_by_filter(
        lambda discovered, _adv: NAME_CONTAINS.lower() in (discovered.name or "").lower(),
        timeout=8.0,
    )
    if not device:
        raise RuntimeError("LOOI not found. Disconnect the official app and restart the robot/Bluetooth.")
    print(f"Found {device.name} at {device.address}")
    return device.address


async def main(args: argparse.Namespace) -> None:
    address = await find_device(args.address)
    log_dir = Path(args.log_dir) / run_id()
    logger = JsonlLogger(log_dir)
    battery_interval_s = args.battery_interval
    if battery_interval_s is None:
        battery_interval_s = (
            1.0
            if (
                args.dock_test
                or args.sensor_test
                or args.physics_test
                or args.passive_test
                or args.fed9_motion_test
                or args.fed9_angle_test
            )
            else DEFAULT_BATTERY_INTERVAL_S
        )
    logger.summary.update({
        "address": address,
        "move_interval_s": MOVE_INTERVAL_S,
        "battery_interval_s": battery_interval_s,
        "quiet_ble": args.quiet_ble,
    })

    stop_event = asyncio.Event()

    def request_stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, request_stop)
        except NotImplementedError:
            pass

    state = ControlState(last_key_time=time.time())
    print(f"Connecting to {address}...")

    async with BleakClient(address, timeout=20.0) as client:
        looi = LooiClient(client, logger, battery_interval_s=battery_interval_s, quiet_ble=args.quiet_ble)
        movement_task: Optional[asyncio.Task] = None
        battery_task: Optional[asyncio.Task] = None
        try:
            await looi.init()
            if args.dock_test:
                await run_dock_test(looi, logger, state)
                return
            if args.sensor_test:
                await run_sensor_test(looi, logger, state)
                return
            if args.physics_test:
                await run_physics_test(looi, logger, state)
                return
            if args.passive_test:
                await run_passive_test(looi, logger, state)
                return
            if args.fed9_motion_test:
                await run_fed9_motion_test(looi, logger, state)
                return
            if args.fed9_angle_test:
                await run_fed9_angle_test(looi, logger, state)
                return
            print_help()
            movement_task = asyncio.create_task(looi.movement_loop(state))
            battery_task = asyncio.create_task(looi.battery_loop())

            last_status = 0.0
            with TerminalMode() as term:
                while not stop_event.is_set():
                    if key_available():
                        keep_running = await handle_key(read_key(), state, looi, logger, term)
                        if not keep_running:
                            break

                    if (
                        state.deadman_enabled
                        and (state.speed != 0 or state.turn != 0)
                        and time.time() - state.last_key_time > state.deadman_timeout_s
                    ):
                        state.stop_motion()
                        logger.event("deadman_stop", state=state.as_dict())
                        print("\nDeadman STOP: no key input for %.1fs" % state.deadman_timeout_s)

                    if time.time() - last_status > 0.5:
                        last_status = time.time()
                        print("\r" + status_line(state, looi)[:220], end="", flush=True)

                    await asyncio.sleep(0.01)
        finally:
            state.stop_motion()
            await looi.shutdown()
            for task in [movement_task, battery_task]:
                if task:
                    task.cancel()
            logger.summary.update({
                "final_state": state.as_dict(),
                "heartbeat_writes": looi.heartbeat_writes,
                "heartbeat_errors": looi.heartbeat_errors,
                "last_battery": looi.last_battery.hex() if looi.last_battery else None,
                "last_fed5": looi.last_fed5.hex() if looi.last_fed5 else None,
                "last_fed9": looi.last_fed9.hex() if looi.last_fed9 else None,
                "last_fed9_decoded": looi.last_fed9_decoded,
            })
            logger.close()
            print(f"\nLogs: {log_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expanded LOOI terminal controller with logs.")
    parser.add_argument("--address", help="BLE address/UUID. If omitted, scan by name containing LOOI.")
    parser.add_argument("--log-dir", default="looi_control_logs", help="Where to write logs.")
    parser.add_argument(
        "--dock-test",
        action="store_true",
        help="Only log attach/remove phone events. No manual movement controls.",
    )
    parser.add_argument(
        "--sensor-test",
        action="store_true",
        help="Guided full sensor mapping. No manual movement controls.",
    )
    parser.add_argument(
        "--physics-test",
        action="store_true",
        help="Guided IMU/head/motor feedback mapping with low-speed motor steps.",
    )
    parser.add_argument(
        "--passive-test",
        action="store_true",
        help="Guided passive feedback mapping: manual head bend, track spin, taps, shake.",
    )
    parser.add_argument(
        "--fed9-motion-test",
        action="store_true",
        help="Guided isolation test for unresolved FED9 type 02 and 0e packets.",
    )
    parser.add_argument(
        "--fed9-angle-test",
        action="store_true",
        help="Guided 45/90/180 degree test for unresolved FED9 type 02 and 0e packets.",
    )
    parser.add_argument(
        "--quiet-ble",
        action="store_true",
        help="Do not print BLE notify/battery noise to terminal; keep full logs in files.",
    )
    parser.add_argument(
        "--battery-interval",
        type=float,
        default=None,
        help="FED8 polling interval in seconds. Default: 1.0 in --dock-test, otherwise 4.0.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main(parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
