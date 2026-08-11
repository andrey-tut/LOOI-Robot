# Experiment Playbook

Use this playbook when collecting new protocol data.

## General rules

1. Run one guided test at a time.
2. Use `--quiet-ble` so terminal prompts stay readable.
3. Start and end each step with Enter only after the physical action is clear.
4. Use `n` to add notes if you deviated from the instruction.
5. Preserve the full log directory.

## Recommended command

```bash
./.venv/bin/python looi_control_lab.py --fed9-angle-test --quiet-ble
```

Then analyze:

```bash
./.venv/bin/python looi_analyze_sensors.py looi_control_logs/<run-id> --csv looi_control_logs/<run-id>/samples.csv
```

## What makes a good experiment issue

Include:

- test command;
- run directory or attached `events.jsonl`;
- exact physical sequence;
- whether phone was attached;
- whether USB power was connected;
- robot firmware/app version if known;
- observed physical behavior.

## Useful experiments still needed

### Phone IMU correlation

Attach the phone and log phone accelerometer/gyroscope at the same time as `FED9`. This could map `FED9 02` axes to physical orientation.

### `FE00` allowlist

Test one known safe-looking payload at a time. Start with light/head gestures, not fast movement.

### USB event repeatability

Repeat cable in/out with battery at different charge levels and phone attached/removed.

### Front touch semantics

Check if `12 00 00` has a release event, multiple pressure levels, or only a pulse.

### Firmware compatibility

Run `--sensor-test` on different LOOI bases and app/firmware versions.
