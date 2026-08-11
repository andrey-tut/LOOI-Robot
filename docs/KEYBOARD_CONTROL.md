# Keyboard Control

`looi_keyboard_control.py` is the recommended entry point for driving the robot. It connects over Bluetooth LE, keeps the movement heartbeat alive, displays compact live state, and writes complete diagnostics to timestamped log files.

## Start

```bash
./.venv/bin/python looi_keyboard_control.py --quiet-ble
```

Close the official LOOI app first. A BLE peripheral normally accepts only one active controller.

Optional arguments:

```bash
./.venv/bin/python looi_keyboard_control.py --help
./.venv/bin/python looi_keyboard_control.py --address <BLE_ADDRESS_OR_UUID>
./.venv/bin/python looi_keyboard_control.py --battery-interval 1.0
./.venv/bin/python looi_keyboard_control.py --log-dir looi_control_logs
```

## Keys

Movement values are persistent: pressing a key changes the current speed or turn value. Forward/backward and turning can therefore be combined. Press `space` at any time to stop both.

| Key | Action |
|---|---|
| `w` / `s` | Increase forward/backward speed. |
| `a` / `d` | Increase left/right turn. |
| `z` | Set forward/backward speed to zero. |
| `c` | Set turning to zero. |
| `space` | Emergency stop: speed and turn to zero. |
| `1..5` | Set movement step to `8`, `16`, `32`, `64`, or `127`. |
| `p` | Short forward pulse using the current step. |
| `y` | Short left-turn pulse using the current step. |
| `t` | Toggle the three-second deadman auto-stop. |
| `i` / `k` | Move the head up/down by the current head step. |
| `u` / `o` / `l` | Head fully up / center / fully down. |
| `[` / `]` | Decrease/increase the head step. |
| `f` | Toggle the front light off/max. |
| `v` / `b` | Decrease/increase light brightness. |
| `g` | Blink the light. |
| `e` | Show the last decoded sensor, battery, and telemetry state. |
| `n` | Add a text note to the log. |
| `h` / `?` | Print keyboard help. |
| `q` | Stop and disconnect. |

## Logs

Every run creates a folder such as:

```text
looi_control_logs/20260812-153000/
├── events.jsonl
├── keys.csv
└── summary.json
```

`events.jsonl` contains BLE reads, writes, notifications, decoded guesses, and errors. `keys.csv` records every key, resulting movement/head/light state, and notes. This makes a failed or surprising run reproducible without flooding the terminal.

## Other entry points

| File | Purpose |
|---|---|
| `looi_control_lab.py` | Guided sensor, dock, motion, and FED9 experiments. |
| `looi_analyze_sensors.py` | Analyze one or more recorded experiment runs. |
| `wasd.py` | Original compact keyboard proof of concept, kept for reference. |
