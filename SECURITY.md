# Security Policy

This is an experimental hardware-control project. There is no formal security support window yet.

## Reporting concerns

Please open a GitHub issue for:

- unsafe default robot movement;
- BLE commands that can unexpectedly stress motors;
- scripts that leak local paths or logs unintentionally;
- documentation that encourages unsafe testing.

If a concern includes sensitive personal data from logs, remove or redact it before posting publicly.

## Supported versions

Only the current `main` branch is considered for fixes.

## Safety-sensitive areas

- arbitrary BLE writes;
- `FE00` scripted gestures;
- any future AI tool that can move the robot;
- mobile app permissions and camera/microphone handling.
