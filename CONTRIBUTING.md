# Contributing

Contributions are welcome, especially repeatable experiments and clear protocol notes.

## Good contributions

- New logs from guided tests.
- Corrections to protocol tables.
- Safer BLE abstractions.
- New test modes.
- App UX ideas and permission notes.
- Documentation improvements.
- Small, focused fixes.

## Before opening a pull request

1. Keep changes focused.
2. Do not commit `looi_control_logs/`, `.venv/`, or `__pycache__/`.
3. Run syntax checks:

```bash
python -m py_compile looi_control_lab.py looi_analyze_sensors.py wasd.py
```

4. If changing protocol decoding, include a log sample or explain the test.

## Experiment reports

For reverse-engineering findings, include:

- command used;
- run directory or attached `events.jsonl`;
- physical action sequence;
- expected vs actual result;
- robot firmware/app version if known.

## Safety

Do not submit code that sends arbitrary unknown motor/gesture packets by default. Experimental commands must be behind an explicit flag and documented in [Safety](docs/SAFETY.md).
