# FED9 Telemetry Decode

`FED9` is the primary notification stream. The current decoder lives in `looi_control_lab.py` as `decode_fed9()` and is used by `looi_analyze_sensors.py`.

## Packet table

| Raw pattern | Decoded kind | Confidence | Notes |
|---|---|---:|---|
| `11 01 00` | `boot_init_complete` | High | Seen after initialization. |
| `05` | `phone_dock_state attached` | High | Repeated attach/remove tests. |
| `06` | `phone_dock_state removed` | High | Repeated attach/remove tests. |
| `01 b1 b2 b3 b4` | `cliff_contact` | High | Four lower sensors, active-low. |
| `09 v` | `left_side_touch` | High | `v=1` press, `v=0` release. |
| `0A v` | `right_side_touch` | High | `v=1` press, `v=0` release. |
| `0B v` | `external_power_event` | Medium-high | Observed around USB-C plug/unplug. |
| `12 00 00` | `front_touch` | High | Front center touch. |
| `02 a b` | `imu_like` | Medium | Two signed 8-bit axes. |
| `0E x y` | `motion_or_encoder_candidate` | Low-medium | Motion/attitude/event-like scalar. |

## Lower cliff/contact sensors

Packet:

```text
01 FL FR RL RR
```

The values are active-low:

```text
0 = triggered / over cliff / no surface
1 = safe / surface detected
```

Confirmed mapping:

| Raw | Meaning |
|---:|---|
| `01 01 01 01 01` | All four sensors normal. |
| `01 00 01 01 01` | Front-left active. |
| `01 01 00 01 01` | Front-right active. |
| `01 01 01 00 01` | Rear-left active. |
| `01 01 01 01 00` | Rear-right active. |

## Touch sensors

| Raw | Meaning |
|---:|---|
| `09 01` | Left side touch press. |
| `09 00` | Left side touch release. |
| `0A 01` | Right side touch press. |
| `0A 00` | Right side touch release. |
| `12 00 00` | Front center touch event. |

The front event currently appears as a pulse-like notification, not as a clean press/release pair.

## Phone mount / dock state

| Raw | Meaning |
|---:|---|
| `05` | Phone attached/docked to the robot head. |
| `06` | Phone removed/undocked. |

This is useful for a future phone-mounted app: the app can change UI, permissions, or behavior when the phone is physically attached.

## Power events

| Source | Raw | Meaning |
|---|---:|---|
| `FED8` | `PP 00` | Battery mode. `PP` is percent. |
| `FED8` | `PP 01` | USB/external power present. |
| `FED9` | `0B 01` | External power connected event. |
| `FED9` | `0B 00` | External power removed event. |

## `FED9 02`: IMU-like axes

Packet:

```text
02 A B
```

Best current interpretation:

```text
A = signed int8 axis A
B = signed int8 axis B
```

Examples from tests:

```text
02 ff b2 -> A=-1,  B=-78
02 dc 9e -> A=-36, B=-98
02 00 00 -> A=0,   B=0
```

Known behavior:

- Strongly appears during nose-down pitch tests.
- One axis may stay near `-1` while the other changes smoothly.
- At 90-degree/vertical positions values can wrap or normalize through large signed-byte transitions.
- Not observed as a reliable wheel encoder.

Useful app-level events:

- `tilt_nose_down_detected`
- `robot_vertical_or_falling_candidate`
- `orientation_changed`

Not safe yet:

- precise degree estimation;
- compass/yaw estimation;
- head-angle feedback.

## `FED9 0E`: motion/attitude-like scalar

Packet:

```text
0E X Y
```

The analyzer currently prints little-endian and big-endian interpretations. Little-endian often looks useful for low ranges:

```text
0e 42 00 -> 66
0e 75 01 -> 373
0e ff ff -> -1 / sentinel-like value
0e d3 05 -> 1491
```

Known behavior:

- Appears during yaw, roll, slide, and some vertical position changes.
- Does not appear consistently when a track is rotated by hand while the body is fixed.
- Can emit sentinel/wrap-like values such as `ffff`, `0104`, `d305`.
- Does not look like a clean wheel encoder.
- Does not look like a simple `0..360` heading.

Recommended use for now:

- motion activity detection;
- “robot was moved/rotated” event;
- debugging signal in logs.

Avoid using it as:

- precise odometry;
- motor load/current;
- exact yaw angle.

## Log analysis workflow

Run a guided test:

```bash
./.venv/bin/python looi_control_lab.py --fed9-angle-test --quiet-ble
```

Analyze latest log:

```bash
./.venv/bin/python looi_analyze_sensors.py
```

Export numeric samples:

```bash
./.venv/bin/python looi_analyze_sensors.py looi_control_logs/<run-id> --csv fed9_samples.csv
```

CSV columns include:

- `run`
- `step`
- `t`
- `t_rel`
- `type`
- `raw`
- `axis_a_i8`
- `axis_b_i8`
- `value_i16_le`
- `value_i16_be`
- `b1`
- `b2`
