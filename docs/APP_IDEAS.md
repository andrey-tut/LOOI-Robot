# Future Mobile App Ideas

A separate app is planned. This document collects product and technical ideas so contributors can suggest features before implementation starts.

## Core app concept

Turn LOOI into a programmable, funny, expressive desk companion:

```text
phone screen = face, camera, microphone, speaker, AI brain
LOOI base    = movement, head pitch, light, touch/cliff/dock sensors
```

## Minimum viable app

- BLE scan/connect/disconnect.
- LOOI handshake and health status.
- Joystick control with speed limit.
- Head pitch slider.
- Light brightness slider.
- Battery and USB indicator.
- Live sensor panel.
- Emergency stop always visible.
- “Phone attached” mode switch when `FED9 05/06` changes.

## Useful permissions

### Android

- `BLUETOOTH_SCAN`
- `BLUETOOTH_CONNECT`
- `ACCESS_FINE_LOCATION` for BLE scan compatibility
- `CAMERA`
- `RECORD_AUDIO`
- `POST_NOTIFICATIONS`

### iOS

- `NSBluetoothAlwaysUsageDescription`
- `NSCameraUsageDescription`
- `NSMicrophoneUsageDescription`
- notification permission
- background modes only if a real foreground/background UX is designed

## Flutter plugin candidates

| Need | Candidate packages |
|---|---|
| BLE | `flutter_blue_plus`, `flutter_reactive_ble` |
| Camera | `camera` |
| Device sensors | `sensors_plus` |
| Permissions | `permission_handler` |
| TTS | `flutter_tts` or cloud TTS |
| Speech recognition | `speech_to_text`, platform APIs, or cloud speech |
| Local notifications | `flutter_local_notifications` |
| Animations | Flutter CustomPainter, Rive, Lottie |

## AI features

Potential modes:

- voice companion;
- visual Q&A using camera frames;
- tool-calling agent that can move, stop, blink, nod, and react to touch;
- local memory of preferences and names;
- safe “ask before moving” mode;
- child-friendly game mode.

Example robot tools:

```json
{
  "move": { "speed": 20, "turn": 0, "duration_ms": 500 },
  "stop": {},
  "set_head": { "value": 90 },
  "set_light": { "brightness": 180 },
  "play_gesture": { "id": "happy_wiggle" },
  "say": { "text": "I found the edge!" }
}
```

## Interaction ideas

### Desk pet

- reacts to touch;
- sleeps when idle;
- wakes when phone attached;
- looks “curious” when moved;
- shows mood based on battery and recent interactions.

### Sensor games

- tap left/right to answer questions;
- front touch as “boop”;
- cliff sensors as mini obstacle-game inputs;
- tilt challenges using `FED9 02`.

### AI remote-control assistant

- “come closer”;
- “turn around”;
- “blink if you hear me”;
- “look surprised and back away”;
- “patrol my desk but do not fall off.”

### Camera personality

- sees objects and comments on them;
- recognizes a face or hand wave;
- turns toward sound or visual target approximately;
- reacts when placed on the base.

### Notifications

- reminders with robot animation;
- battery alerts;
- “robot touched” notifications;
- playful “I was picked up” events.

## Safety UX requirements

- Big stop button.
- Speed limit slider.
- Default slow mode.
- Stop on disconnect.
- Stop when app goes background unless explicitly allowed.
- Do not run unknown `FE00` gestures by default.
- Require user confirmation before AI-initiated movement.

## Community feature requests wanted

Good issue titles:

- `App idea: touch-based quiz game`
- `App idea: LOOI as Pomodoro desk companion`
- `App idea: camera object reactions`
- `App idea: safe FE00 gesture pack`
- `App idea: kids mode restrictions`
- `Protocol idea: map FED9 02 to phone IMU`
