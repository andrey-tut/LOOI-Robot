# Safety Notes

This project controls real robot motors over BLE. Treat every experiment as hardware control, not as a harmless software-only script.

## Basic safety rules

- Start with low speed.
- Keep the robot on a clear surface.
- Keep one hand close enough to pick it up or stop it.
- Do not run near stairs, pets, liquids, or fragile objects.
- Do not hard-block the tracks/wheels.
- Do not test unknown packets at full speed.
- Stop immediately if motion does not match expectation.

## Software safety rules

- Always send `FED0 00 00` on shutdown.
- Stop movement on disconnect or heartbeat error.
- Keep an emergency stop key/button.
- Keep a deadman timeout for manual control.
- Log unknown experiments.
- Keep `FE00` and `FF02` behind explicit experimental flags.

## AI safety rules for a future app

- AI should not move the robot without user-visible state.
- AI movement should default to short, slow motions.
- AI must have a stop tool and safety constraints.
- User should be able to disable movement tools while keeping voice/chat active.
- Do not let an LLM generate arbitrary BLE payloads.

## Hardware unknowns

The following are not proven enough for safety features:

- motor current/load telemetry;
- wheel odometry;
- exact head-position feedback;
- exact yaw/heading;
- safe behavior of arbitrary `FE00` packets;
- behavior of `FF02` boost motor commands.

Do not build collision avoidance, odometry, or motor-stall protection on unverified telemetry.
