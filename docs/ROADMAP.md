# Roadmap

The project is moving from proof-of-concept control toward a reusable SDK and, later, a mobile companion app.

## Phase 1 — Stabilize Python research tools

Status: in progress.

- [x] Stable BLE handshake.
- [x] Continuous movement heartbeat.
- [x] Keyboard control with speed/turn mixing.
- [x] Head and light controls.
- [x] JSONL logging.
- [x] Guided sensor tests.
- [x] Guided `FED9 02/0e` experiments.
- [x] Log analyzer and CSV export.
- [ ] Clean Python package structure.
- [ ] Unit tests for packet decoding.
- [ ] Safer reconnect loop.
- [ ] Structured command API separate from terminal UI.

## Phase 2 — LOOI Python SDK

Planned package shape:

```text
looi/
  ble.py          # scan/connect/handshake/read/write
  protocol.py     # UUIDs and packet encode/decode
  controller.py   # movement/head/light high-level API
  sensors.py      # typed FED9 events
  gestures.py     # allowlisted FE00 experiments
  logging.py      # JSONL helpers
```

Potential API:

```python
async with LooiRobot.connect() as looi:
    await looi.move(speed=30, turn=0)
    await looi.head.center()
    await looi.light.set(180)
    async for event in looi.events():
        print(event)
```

## Phase 3 — Safe experimental gestures

- [ ] Add `FE00` characteristic discovery.
- [ ] Implement an allowlisted gesture registry.
- [ ] Add `--gesture-test` mode.
- [ ] Start with low-risk LED/head gestures.
- [ ] Document every tested gesture with physical result.
- [ ] Avoid arbitrary payload sends in default mode.

## Phase 4 — Mobile companion app

Target: Flutter iOS/Android app.

Core modules:

- BLE session manager;
- robot face / emotion engine;
- joystick and gesture controls;
- sensor event timeline;
- voice mode;
- camera mode;
- AI tool-calling layer;
- safety settings;
- community gesture packs.

See [App Ideas](APP_IDEAS.md).

## Phase 5 — Robot behaviors and games

Ideas:

- desk pet mode;
- follow-the-light or hide-and-seek style games;
- touch-reactive emotions;
- cliff sensor mini-games;
- “guard mode” notification toy;
- voice-controlled obstacle course;
- mood-based animations;
- daily reminder companion.

## Phase 6 — Documentation and community

- [x] Protocol documentation.
- [x] Open-question tracking.
- [x] Experiment issue template.
- [ ] Short demo videos/GIFs.
- [ ] Wiring-free quickstart screenshots.
- [ ] Compatibility matrix by robot firmware/app version.
- [ ] Community-contributed logs and findings.

## Non-goals for now

- Autonomous navigation based on unverified odometry.
- Hard motor stress/load experiments.
- Circumventing safety limits.
- Publishing decompiled proprietary app code.
