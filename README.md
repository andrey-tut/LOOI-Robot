# LOOI Robot Reverse Engineering Lab

[English](README.md) · [Українські дослідницькі нотатки](LOOI_RESEARCH_UA.md)

[![CI](https://github.com/andrey-tut/LOOI-Robot/actions/workflows/python.yml/badge.svg)](https://github.com/andrey-tut/LOOI-Robot/actions/workflows/python.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![BLE](https://img.shields.io/badge/Bluetooth%20LE-reverse%20engineering-0082FC?logo=bluetooth&logoColor=white)](docs/PROTOCOL.md)
[![Bleak](https://img.shields.io/badge/Bleak-tested%20on%20macOS-111111)](https://github.com/hbldh/bleak)
[![Status](https://img.shields.io/badge/status-experimental-orange)](docs/OPEN_QUESTIONS.md)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/andrey-tut/LOOI-Robot)](https://github.com/andrey-tut/LOOI-Robot/issues)
[![GitHub stars](https://img.shields.io/github/stars/andrey-tut/LOOI-Robot?style=flat)](https://github.com/andrey-tut/LOOI-Robot/stargazers)

Unofficial Python control and research toolkit for the **LOOI Robot** base. This project documents the Bluetooth LE protocol, provides keyboard control, guided sensor/telemetry experiments, and a foundation for a future mobile companion app.

The goal is not only to drive the robot. The goal is to turn LOOI into an open, playful, programmable robot platform.

> This is an unofficial community project. It is not affiliated with Tangible Future or the official LOOI app.

## What works today

| Area | Status | Notes |
|---|---:|---|
| BLE connection and handshake | Verified | Includes the `FEDA` activation sequence and macOS service-discovery workaround. |
| Movement | Verified | `FED0` two-byte signed speed/turn control with a 30 ms heartbeat. |
| Head pitch | Verified | `FED1` one-byte command, center is `0x5A`. |
| Headlight / front light | Verified | `FED2`, brightness-like byte. |
| Battery and USB state | Verified | `FED8`, plus `FED9 0b` power events. |
| Phone dock / mount state | Verified | `FED9 05` attached, `FED9 06` removed. |
| Lower cliff/contact sensors | Verified | Four active-low values in `FED9 01`. |
| Touch sensors | Verified | Left side, right side, and front center events. |
| IMU-like telemetry | Partially decoded | `FED9 02` is two signed 8-bit axes; `FED9 0e` is motion/attitude-like. |
| `FE00` scripted gestures | Not integrated yet | Known sniffed payloads exist, but a safe player is still planned. |

See [Protocol](docs/PROTOCOL.md), [FED9 Telemetry](docs/FED9_TELEMETRY.md), and [Open Questions](docs/OPEN_QUESTIONS.md) for details.

## Repository layout

```text
.
├── looi_keyboard_control.py  # Recommended keyboard controller
├── looi_control_lab.py       # Guided BLE experiments and shared protocol code
├── looi_analyze_sensors.py   # JSONL log analyzer for sensor/telemetry tests
├── wasd.py                   # Original compact keyboard PoC
├── connect.py                # Earlier connection/control experiment
├── looi_probe.py             # Early probing script
├── LOOI_RESEARCH_UA.md       # Ukrainian research notes and app ideas
├── docs/                     # Protocol, usage, roadmap, safety, app concepts
└── .github/                  # Issue templates, PR template, CI syntax check
```

Generated logs are written to `looi_control_logs/` and are intentionally ignored by git.

## Choose a tool

| Goal | Run | Notes |
|---|---|---|
| Drive the robot | `python looi_keyboard_control.py --quiet-ble` | Recommended controller: movement, combined turns, head, light, live state, logs. |
| Run a guided experiment | `python looi_control_lab.py <test flag> --quiet-ble` | Sensor, dock/power, passive feedback, IMU, and angle protocols. |
| Analyze recorded data | `python looi_analyze_sensors.py [run folders]` | Groups events by test step and exports optional CSV. |
| Inspect raw commands | `python looi_interactive_probe.py` | Advanced experimental probe; read safety notes first. |
| Read the minimal example | `wasd.py` | Original compact proof of concept, intentionally kept simple. |

## Quick start

### 1. Install

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

If you only need the core dependency:

```bash
./.venv/bin/pip install bleak
```

### 2. Disconnect the official app

Only one BLE central should control the robot at a time. Close the official LOOI app before running these scripts.

### 3. Drive with the keyboard

```bash
./.venv/bin/python looi_keyboard_control.py --quiet-ble
```

This is the recommended everyday controller. Movement values are persistent, so pressing `w` and then `a` combines forward motion with a left turn. `space` always stops both.

Useful keys:

| Key | Action |
|---|---|
| `w` / `s` | Increase/decrease forward speed |
| `a` / `d` | Increase/decrease turn |
| `space` | Emergency stop |
| `1..5` | Change speed/turn step |
| `i` / `k` | Move head up/down |
| `u` / `o` / `l` | Head raw up / center / down |
| `f`, `v`, `b`, `g` | Light toggle, dim, brighten, blink |
| `e` | Print last sensor state |
| `n` | Add a note to the current log |
| `q` | Stop and quit |

Full guide: [Keyboard Control](docs/KEYBOARD_CONTROL.md).

### 4. Run guided experiments

```bash
# Full mapped sensor validation
./.venv/bin/python looi_control_lab.py --sensor-test --quiet-ble

# Phone mount and USB power events
./.venv/bin/python looi_control_lab.py --dock-test --quiet-ble

# Passive movement / manual feedback tests
./.venv/bin/python looi_control_lab.py --passive-test --quiet-ble

# FED9 type 02 / 0e isolation
./.venv/bin/python looi_control_lab.py --fed9-motion-test --quiet-ble

# 45/90/180 degree angle-oriented test
./.venv/bin/python looi_control_lab.py --fed9-angle-test --quiet-ble
```

### 5. Analyze logs

```bash
./.venv/bin/python looi_analyze_sensors.py
./.venv/bin/python looi_analyze_sensors.py looi_control_logs/20260705-141346 --csv fed9_angle.csv
```

## BLE protocol summary

| Characteristic | Direction | Purpose |
|---|---|---|
| `FED0` | Write | Movement: `[speed, turn]` signed bytes. |
| `FED1` | Write | Head pitch command. |
| `FED2` | Write | Headlight / front light brightness. |
| `FED5` | Notify | Subscribed for compatibility; observed mostly quiet locally. |
| `FED8` | Read | Battery percent and USB/external-power status. |
| `FED9` | Notify | Boot, cliff/contact, touch, phone dock, power, IMU/motion telemetry. |
| `FEDA` | Write | Handshake / activation. |
| `FE00` | Write | Experimental scripted gestures from sniffed traffic. |

Minimal connection sequence:

1. Scan and connect to a device whose name contains `LOOI`.
2. Optionally read `2A29` to warm up BLE/service discovery on macOS.
3. Write `01` to `FEDA`.
4. Subscribe to `FED5` and `FED9` notifications.
5. Write `03` to `FEDA`.
6. Write `FED0 00 00` and keep writing movement state roughly every 30 ms.
7. Poll `FED8` periodically for battery/keep-alive information.

Full notes: [Protocol](docs/PROTOCOL.md).

## Safety

The scripts directly command a physical robot. Use a clear table/floor area, start with low speed, keep one hand near the robot, and treat every unknown packet as experimental. Do not block motors hard during tests. See [Safety](docs/SAFETY.md).

## Future app direction

A separate mobile app is planned. Candidate features:

- Flutter iOS/Android BLE controller.
- Animated robot face and emotion engine.
- Voice interaction, TTS, camera context, and optional OpenAI-powered tool calls.
- Sensor-reactive games and pet-like behaviors.
- Community gesture packs and safe `FE00` scripted actions.
- Local-first privacy mode with optional cloud AI.

See [Mobile App Ideas](docs/APP_IDEAS.md) and [Roadmap](docs/ROADMAP.md). Ideas, experiments, logs, and protocol corrections are welcome.

## Contributing

The most useful contributions are repeatable experiments, logs with notes, safer command abstractions, and mobile-app UX ideas. Please read [Contributing](CONTRIBUTING.md) before opening an issue or pull request.

Have an app or behavior idea but no implementation yet? Open an [app/behavior idea](https://github.com/andrey-tut/LOOI-Robot/issues/new?template=app_idea.yml). Unknown packets and contradictory observations are welcome when accompanied by a reproducible experiment.

## Related community research

- [`splattydoesstuff/sooperchargeforbots`](https://github.com/splattydoesstuff/sooperchargeforbots) — useful `FE00` sniffed command list and app reverse-engineering notes.
- [`andrey-tut/LOOI-Robot`](https://github.com/andrey-tut/LOOI-Robot) — this repository.

## License

GPL-3.0. See [LICENSE](LICENSE).
