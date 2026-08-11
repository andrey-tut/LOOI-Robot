# LOOI BLE Protocol Notes

This document describes the currently known Bluetooth LE protocol for the LOOI Robot base. All findings are experimental and based on local testing with Python/Bleak plus community sniffing notes.

## Device discovery

The scripts scan for a BLE peripheral whose advertised name contains:

```text
LOOI
```

If scan fails:

- close the official LOOI app;
- restart Bluetooth;
- restart the robot base;
- pass `--address` if you already know the BLE address/UUID.

## Important characteristics

All short UUIDs are under the standard Bluetooth base UUID:

```text
0000xxxx-0000-1000-8000-00805f9b34fb
```

| Short UUID | Full UUID | Direction | Status | Meaning |
|---|---|---|---:|---|
| `FED0` | `0000fed0-0000-1000-8000-00805f9b34fb` | Write | Verified | Movement control. |
| `FED1` | `0000fed1-0000-1000-8000-00805f9b34fb` | Write | Verified | Head pitch command. |
| `FED2` | `0000fed2-0000-1000-8000-00805f9b34fb` | Write | Verified | Headlight/front light. |
| `FED5` | `0000fed5-0000-1000-8000-00805f9b34fb` | Notify | Subscribed | Kept for compatibility; observed quiet in local tests. |
| `FED8` | `0000fed8-0000-1000-8000-00805f9b34fb` | Read | Verified | Battery and power status. |
| `FED9` | `0000fed9-0000-1000-8000-00805f9b34fb` | Notify | Verified | Main telemetry stream. |
| `FEDA` | `0000feda-0000-1000-8000-00805f9b34fb` | Write | Verified | Activation handshake. |
| `FE00` | `0000fe00-0000-1000-8000-00805f9b34fb` | Write | Experimental | Scripted gesture/action channel. |
| `FF02` | `0000ff02-0000-1000-8000-00805f9b34fb` | Write | Unverified | Mentioned by community as boost motor; not tested here. |
| `2A29` | `00002a29-0000-1000-8000-00805f9b34fb` | Read | Useful | Manufacturer string; helps with macOS service discovery. |

## Initialization sequence

The robot appears to require a specific handshake and notification subscription order.

```text
connect
optional read 2A29
resolve services
write FEDA: 01
subscribe FED5
subscribe FED9
write FEDA: 03
write FED0: 00 00
read FED8
start movement heartbeat
start periodic battery polling
```

This order is implemented in `looi_control_lab.py`.

## Movement: `FED0`

Payload is exactly two signed bytes:

```text
[speed, turn]
```

| Payload | Meaning |
|---:|---|
| `00 00` | Stop / neutral heartbeat. |
| `7F 00` | Maximum forward. |
| `81 00` | Maximum backward (`-127`). |
| `00 7F` | Maximum spin left. |
| `00 81` | Maximum spin right (`-127`). |
| `20 00` | Slow forward. |
| `00 20` | Slow turn. |
| `30 20` | Forward while turning. |

The command must be repeated continuously. Local testing uses roughly **30 ms** between writes.

Recommended abstraction:

```python
set_motion(speed: int, turn: int)  # both -127..127
stop()
drive_for(speed: int, turn: int, duration_s: float)
```

## Head pitch: `FED1`

Payload is one byte.

| Payload | Meaning |
|---:|---|
| `00` | One extreme, observed as up/look-up. |
| `5A` | Center. |
| `FF` | Other extreme, observed as down/nod. |

There is no confirmed head-position feedback. `FED1` should be treated as command-only for now.

## Light: `FED2`

Payload is one byte.

| Payload | Meaning |
|---:|---|
| `00` | Off. |
| `01..FF` | Brightness-like intensity. |
| `FF` | Maximum in local tests. |

Community notes mention `03` as on/off-style activation. Local control supports the full `0..255` range because the base accepts it.

## Battery / power: `FED8`

Observed payload examples:

| Payload | Interpretation |
|---:|---|
| `4A 00` | 74%, no USB/external power. |
| `4A 01` | 74%, USB/external power present. |

The first byte is treated as percent. The second byte is treated as status:

```text
0 = battery
1 = USB/external power
```

## Telemetry: `FED9`

`FED9` is a multiplexed notify stream. The first byte is the packet type.

| Packet | Status | Meaning |
|---|---:|---|
| `11 01 00` | Verified | Boot/init notification after handshake. |
| `01 b1 b2 b3 b4` | Verified | Four lower cliff/contact sensors, active-low. |
| `02 a b` | Partially decoded | IMU-like signed 8-bit axes. |
| `05` | Verified | Phone attached/docked. |
| `06` | Verified | Phone removed/undocked. |
| `09 01/00` | Verified | Left side touch press/release. |
| `0A 01/00` | Verified | Right side touch press/release. |
| `0B 01/00` | Verified | External power event. |
| `0E x y` | Partially decoded | Motion/attitude/event scalar. |
| `12 00 00` | Verified | Front center touch event. |

See [FED9 Telemetry](FED9_TELEMETRY.md) for examples and open questions.

## Scripted gestures: `FE00`

Community sniffing shows a sequence-like gesture channel on `FE00`. Examples include:

- neck down + forward;
- short back;
- rotate left;
- shake;
- forward + LED blink;
- slow recenter head.

This repository does not yet include a `FE00` player because malformed gesture payloads could move the robot unexpectedly. Planned approach:

1. Add an allowlisted gesture registry.
2. Require explicit `--enable-experimental-fe00`.
3. Start with low-risk light/head gestures.
4. Log every payload and physical result.
5. Only then expose gestures to a future app.

## Timing and stability notes

- `FED0` movement writes should use `response=False`.
- `FED2` light writes currently use `response=True` in the lab script.
- `FEDA` writes use `response=True`.
- On macOS, resolving characteristic objects before writes avoids service-discovery issues.
- `FED8` polling is useful both for state and for connection health.
