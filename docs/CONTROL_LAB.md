# Experiment Lab Guide

`looi_control_lab.py` contains guided BLE experiments and the shared protocol implementation. For ordinary keyboard driving, use [`looi_keyboard_control.py`](KEYBOARD_CONTROL.md).

## Direct launch

```bash
./.venv/bin/python looi_control_lab.py --sensor-test --quiet-ble
```

Options:

```bash
./.venv/bin/python looi_control_lab.py --address <BLE_ADDRESS_OR_UUID>
./.venv/bin/python looi_control_lab.py --quiet-ble
./.venv/bin/python looi_control_lab.py --battery-interval 1.0
```

Running the file without a test flag also starts manual mode, but the dedicated `looi_keyboard_control.py` entry point is clearer for everyday use.

## Manual-mode controls

| Key | Action |
|---|---|
| `w` | Increase forward speed. |
| `s` | Increase backward speed. |
| `a` | Increase left turn. |
| `d` | Increase right turn. |
| `z` | Set speed to zero. |
| `c` | Set turn to zero. |
| `space` | Emergency stop speed and turn. |
| `1` | Set step to 8. |
| `2` | Set step to 16. |
| `3` | Set step to 32. |
| `4` | Set step to 64. |
| `5` | Set step to 127. |
| `p` | Short forward pulse. |
| `y` | Short spin-left pulse. |
| `t` | Toggle deadman stop. |
| `i` | Move head up by step. |
| `k` | Move head down by step. |
| `u` | Head raw `0x00`. |
| `o` | Head center `0x5A`. |
| `l` | Head raw `0xFF`. |
| `[` / `]` | Decrease/increase head step. |
| `f` | Toggle light off/max. |
| `v` / `b` | Dim/brighten light. |
| `g` | Quick blink. |
| `e` | Print last BLE sensor state. |
| `n` | Add note to log. |
| `q` | Stop and quit. |

## Guided tests

### Sensor map

```bash
./.venv/bin/python looi_control_lab.py --sensor-test --quiet-ble
```

Maps:

- four lower cliff/contact sensors;
- left side touch;
- right side touch;
- front center touch.

### Dock / power events

```bash
./.venv/bin/python looi_control_lab.py --dock-test --quiet-ble
```

Use this to test:

- phone attached;
- phone removed;
- USB-C connected;
- USB-C disconnected.

### Passive feedback

```bash
./.venv/bin/python looi_control_lab.py --passive-test --quiet-ble
```

Tests whether the base reports:

- manual head bending;
- manual track rotation;
- taps;
- shake.

Current evidence: no direct head-angle feedback and no reliable manual track encoder feedback.

### FED9 motion isolation

```bash
./.venv/bin/python looi_control_lab.py --fed9-motion-test --quiet-ble
```

Focuses on `FED9 02` and `FED9 0e` while avoiding touch/lower sensor noise.

### FED9 angle test

```bash
./.venv/bin/python looi_control_lab.py --fed9-angle-test --quiet-ble
```

Uses simple positions:

- flat idle;
- yaw 90/180 degrees;
- pitch 45 degrees;
- roll 45 degrees;
- vertical/side 90-degree positions.

## Logs

Each run creates:

```text
looi_control_logs/<YYYYMMDD-HHMMSS>/events.jsonl
looi_control_logs/<YYYYMMDD-HHMMSS>/keys.csv
looi_control_logs/<YYYYMMDD-HHMMSS>/summary.json
```

`events.jsonl` is the primary file for reverse engineering. It includes:

- key markers;
- write/read events;
- `FED5` notifications;
- `FED9` notifications;
- battery reads;
- decoded packet guesses.

## Analyzer

```bash
./.venv/bin/python looi_analyze_sensors.py
./.venv/bin/python looi_analyze_sensors.py looi_control_logs/<run-id>
./.venv/bin/python looi_analyze_sensors.py looi_control_logs/<run-id> --csv samples.csv
```

The analyzer groups events by guided-test step and prints unique packet counts, decoded meanings, and numeric summaries for `FED9 02` / `FED9 0e`.
