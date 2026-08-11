# Open Questions and Unverified Areas

This project intentionally separates verified protocol facts from hypotheses. If something is unclear, it should stay documented as unclear.

## High-priority unknowns

### `FED9 0E`

Status: partially decoded.

Current evidence:

- reacts to body movement, yaw, slide, and some roll/pitch changes;
- sometimes emits little-endian-looking values such as `66`, `373`, `1025`, `1491`;
- sometimes emits `ffff`, which looks sentinel-like;
- does not behave like a clean wheel encoder;
- does not behave like a simple heading angle.

Working name:

```text
motion_or_attitude_scalar
```

What is still needed:

- repeatable side-by-side plots from several runs;
- controlled physical jig if exact orientation mapping is desired;
- comparison against phone accelerometer/gyroscope data mounted to the robot.

### `FED9 02`

Status: mostly understood as two signed 8-bit IMU-like axes, but not mapped to physical axes exactly.

Current evidence:

- `02 A B` where `A` and `B` are best interpreted as signed int8;
- strong response during nose-down pitch;
- vertical positions can wrap/normalize through signed-byte limits;
- not useful as precise yaw/compass.

What is still needed:

- correlate with phone IMU while phone is attached;
- collect clean 45/90 degree samples on a jig;
- label physical axes consistently.

## Medium-priority unknowns

### `FE00` scripted gestures

Status: known from community sniffing, not integrated here.

Open questions:

- exact frame structure;
- sequence counters;
- whether payloads are firmware-version dependent;
- which gestures are safe to expose in an app;
- whether LED color effects are only available through `FE00`.

Planned approach:

- allowlist only;
- explicit experimental flag;
- start with light/head-only gestures;
- log and document each payload.

### `FF02` boost motor

Status: mentioned externally, not tested locally.

Risk:

- may bypass safe slow motor behavior;
- could cause unexpected movement;
- may not exist on all firmware revisions.

Recommendation: leave disabled until there is a clear need.

### Head position feedback

Status: not observed.

Current evidence:

- `FED1` commands head pitch;
- manual head movement did not produce a reliable telemetry signal;
- `FED9 02/0e` can change when the body moves, but not enough to claim head-angle feedback.

Recommendation: app should track commanded head position internally, not assume actual feedback.

### Track encoders / motor load

Status: not observed.

Current evidence:

- manual left-track spin with body fixed produced no events;
- manual right-track spin produced weak `0e` events likely caused by body micro-movement;
- motor resistance tests did not produce enough evidence for load/current telemetry.

Recommendation: do not build odometry or stall detection on current telemetry.

## Lower-priority unknowns

- Whether `FED5` has firmware-specific sensor reports.
- Whether `FED2` supports only brightness or more light modes.
- Whether `0B 00` is consistently emitted on every cable unplug event.
- Whether front touch has release semantics or only pulse semantics.
- Whether phone dock detection can be used to enable charging behavior from software. Current evidence does not prove software-controlled charging.

## How to contribute useful data

When testing an unknown:

1. Use a guided test mode when possible.
2. Keep `--quiet-ble` enabled so terminal output stays readable.
3. Add notes with `n` if something unusual happens.
4. Save the whole log directory, not just screenshots.
5. Open an experiment issue using the template.
6. Include robot firmware/app version if known.
