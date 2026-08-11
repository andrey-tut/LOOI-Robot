# LOOI robot: дослідження протоколу, мобільної архітектури та ідей

Дата: 2026-07-05

## Що я перевірив

Локально:
- `wasd.py` - твій робочий Python-контролер через `bleak`.
- `connect.py` - попередній race-mode контролер.
- `looi_probe.py`, `looi_lab.csv`, `looi_probe_log.csv` - старі проби, частково зламані помилкою BLE service discovery.

GitHub:
- [andrey-tut/LOOI-Robot](https://github.com/andrey-tut/LOOI-Robot) - Python PoC, фактично той самий шлях, що й твій `wasd.py`.
- [splattydoesstuff/sooperchargeforbots](https://github.com/splattydoesstuff/sooperchargeforbots) - документація reverse engineering, `FE00` rich commands, список sniffed команд.
- [novolei/ulooi](https://github.com/novolei/ulooi) - найкращі практичні findings: GATT topology, `FED9` telemetry decode, cliff lockout, iOS CoreBluetooth архітектура.
- [GrinZero/super-looi](https://github.com/GrinZero/super-looi) - Expo/React Native app + TypeScript SDK, voice/memory/perception/device tools.
- [dmvvilela/haze_bot_app](https://github.com/dmvvilela/haze_bot_app) - Flutter face app: емоції, TTS, локальна AI-модель, sounds, game mechanics.

Офіційні docs:
- OpenAI Realtime/voice: [Realtime and audio](https://developers.openai.com/api/docs/guides/realtime), [Voice agents](https://developers.openai.com/api/docs/guides/voice-agents).
- OpenAI tools/vision: [Responses API migration](https://developers.openai.com/api/docs/guides/migrate-to-responses), [Images and vision](https://developers.openai.com/api/docs/guides/images-vision), [Function calling](https://developers.openai.com/api/docs/guides/function-calling).
- Flutter BLE/plugins: [flutter_blue_plus](https://pub.dev/packages/flutter_blue_plus), [flutter_reactive_ble](https://pub.dev/packages/flutter_reactive_ble), [camera](https://pub.dev/packages/camera), [permission_handler](https://pub.dev/packages/permission_handler), [speech_to_text](https://pub.dev/packages/speech_to_text).

## Короткий висновок

LOOI база достатньо відкрита для свого додатку. Найнадійніший шар зараз: BLE primitive control через `FED0/FED1/FED2/FED8/FED9/FEDA`. Це дає рух гусеничної/колісної бази, нахил голови, світло, батарею, сенсорні/telemetry notify, touch/cliff/IMU-подібні події.

`FE00` rich command channel потенційно дає готові анімаційні жести: forward+neck, shake, red/blue LED blink, quick back, recenter head. Але він ще не повністю розшифрований, тому його краще тримати як "experimental gestures", не як базовий motor API.

Flutter-додаток реалістичний для iOS + Android. Основні права: Bluetooth, Location на Android для BLE scan, Camera, Microphone, Notifications, Local Network якщо буде локальний сервер/desktop bridge. Найбільший ризик: не Flutter, а BLE timing, фонова робота iOS і правильний heartbeat.

## BLE підключення

Надійна послідовність з твого `wasd.py`, `andrey-tut`, `ulooi`:

1. Scan device by name: `LOOI`, часто `LOOI Robot`.
2. Connect BLE.
3. Optional read `2A29` manufacturer/device info. На macOS/iOS це допомагає "розбудити" service discovery/cache.
4. Discover services and characteristics.
5. Write `01` to `FEDA`.
6. Subscribe notify на `FED5` sensors і `FED9` telemetry.
7. Write `03` to `FEDA`.
8. Start movement heartbeat: write `FED0` кожні приблизно `30ms`, навіть `00 00`.
9. Read `FED8` battery кожні приблизно `4s` як keep-alive.

Критично:
- Без handshake робот може приймати деякі writes, але швидко disconnect.
- Без notify subscribe між `FEDA=01` і `FEDA=03` connection нестабільний.
- Рухові команди треба писати `withoutResponse`.
- Якщо база піднята/висить над столом, cliff sensor може блокувати motors. Це виглядає як "BLE працює, але не їде".

## GATT / характеристики

| UUID | Що робить | Статус |
|---|---|---|
| `0000fed0-...` | рух `[speed, turn]`, signed int8 | verified |
| `0000fed1-...` | pitch голови, 1 byte angle | verified |
| `0000fed2-...` | фара/headlight, 1 byte brightness | verified у `ulooi`, у `sooper` описано як on/off |
| `0000fed5-...` | sensors notify | subscribed, формат гірше вивчений |
| `0000fed8-...` | battery read, приклад `[percent, status]` | verified |
| `0000fed9-...` | telemetry notify: boot/cliff/touch/IMU-like | verified у `ulooi` |
| `0000feda-...` | handshake writes | verified |
| `0000fe00-...` | rich 17-byte commands / gestures | experimental |
| `0000ff02-...` | "boost motor" у `sooper`, але `ulooi` не підтвердив | не варто покладатись |

## Рух бази

Primitive command на `FED0`: 2 bytes `[speed, turn]`, обидва signed int8.

| Дія | Hex | Пояснення |
|---|---:|---|
| Stop | `00 00` | heartbeat safe default |
| Forward max | `7F 00` | +127 speed |
| Backward max | `81 00` | -127 speed у signed int8 |
| Spin left max | `00 7F` | +127 turn |
| Spin right max | `00 81` | -127 turn |
| Drift forward-left | `46 46` | speed + turn разом |
| Slow forward | `20 00` | приблизно 25% speed |
| Slow turn | `00 20` | мʼякий поворот |

Практично краще мати API:

```text
setMotion(speed: -127..127, turn: -127..127)
stop()
driveFor(speed, turn, durationMs)
joystick(x, y) -> speed/turn
```

Не робити single-shot movement для UI. Потрібен loop, який тримає поточний motion state і шле його кожні `30ms`.

## Голова

`FED1`: 1 byte.

| Дія | Hex | Нотатка |
|---|---:|---|
| Center | `5A` | у твоєму `wasd.py`; `ulooi` теж трактує як центр |
| Look up | `00` | pitch up |
| Look down / nod | `FF` | у `ulooi` може auto-return to center |
| Intermediate | `30`, `80`, `B0` | треба доміряти hold/gesture behavior |

Важливо: це pitch, не yaw. Горизонтальний "поворот голови" фактично робиться колесами через `turn`.

## Світло / фари

`FED2`: 1 byte.

`sooperchargeforbots` пише `00=off`, `03=on`, але `ulooi` на реальному iPhone виявив градієнт яскравості, тобто:

```text
00 = off
01..FF = brightness
FF = likely max
```

API краще робити не `setLight(bool)`, а:

```text
setBrightness(0..255)
pulse(color/brightness, ms)
blink(pattern)
lipsyncLight(envelope)
```

Колір не підтверджений для `FED2`; `FE00` sniffed пакети мають red/blue LED effects, але формат ще не чистий.

## Батарея

`FED8`: read. За `ulooi` приклад `35 00` = 53%, тобто перший byte може бути percent.

Keep-alive: читати раз на `4s`. UI:
- battery badge;
- safe shutdown below threshold;
- auto-dim lights;
- stop movement on disconnect / low battery.

## Сенсори

`FED9` за `ulooi` - multiplexed telemetry stream, де перший byte це packet type.

| Type | Payload | Ймовірне значення |
|---|---|---|
| `11 01 00` | fixed 3 bytes | boot/init status після handshake |
| `01 b1 b2 b3 b4` | 5 bytes | cliff / contact binary state |
| `02 b1 b2` | 3 bytes | IMU-like signed int16, можливо tilt/motion |
| `09 b1` | 2 bytes | touch press/release |

Cliff:
- `01 01 01 01 01` - всі колеса/сенсори на поверхні.
- `01 00 01 01 01` - передній cliff підтверджений.
- back/left/right mapping ще не повністю доведений.

Touch:
- `09 01`, `09 00` зʼявляються при дотику до боків/корпусу.
- Не доведено, чи є окремі left/right zones.

Що варто доробити тестами:
- Поставити LOOI на край столу по одному колесу і логувати `FED9`.
- Окремо торкати лівий/правий бік, верх/низ, док/магніт і дивитись `09`.
- Крутити/нахиляти базу у фіксованих позах і розшифрувати `02`.

## FE00 rich commands

`FE00` - експериментальний канал з 17-byte або довшими sequence-like payloads. `sooperchargeforbots` описує його як script/animation mode: packets працюють як кадри gesture sequence.

Приклади зі sniffed list:

| Назва | Characteristic | Payload |
|---|---|---|
| Neck down + forward | `FE00` | `00000000010032030a0a010a32030f0a010f2a03` |
| Short back | `FE00` | `000100000101f501030001ff0001` |
| Rotate left | `FE00` | `0202640002641e036aeb0271eb0273320379f502` |
| Forward + red LED blink | `FE00` | `030e21ff05000000239901230005000000252a01` |
| Blue LED | `FE00` | `110e7d2f03ff0001ff0003` |
| Slow recenter head | `FE00` | `00100000010032030a0001ff00010a3203ff0003` |

Необхідна обережність:
- Sequence counter може бути обовʼязковим.
- Деякі payloads довші за 17 bytes, тобто це не один простий frame.
- Пакети можуть залежати від firmware/app version.
- Я б зробив "gesture registry" з allowlist, а не генератор довільних `FE00` команд.

## Flutter feasibility

Flutter може потягнути все, що потрібно:

| Функція | Реалістичність | Варіанти |
|---|---|---|
| BLE scan/connect/write/notify | так | `flutter_blue_plus` або `flutter_reactive_ble` |
| Camera preview/photo/stream | так | `camera` |
| Microphone recording | так | `record`, `speech_to_text`, platform channels |
| TTS | так | `flutter_tts`, OpenAI TTS через backend |
| Notifications | так | `flutter_local_notifications` / native |
| Sensors/orientation | так | `sensors_plus` / platform APIs |
| OpenAI voice agent | так | краще через backend + Realtime/WebRTC або streaming |
| Background BLE | обмежено | iOS foreground-first, Android простіше |
| Always-on wakeword | складно | батарея, privacy, iOS background limits |

Android permissions:
- `BLUETOOTH_SCAN`
- `BLUETOOTH_CONNECT`
- `ACCESS_FINE_LOCATION` для scan на багатьох BLE сценаріях
- `CAMERA`
- `RECORD_AUDIO`
- `POST_NOTIFICATIONS`

iOS permissions:
- `NSBluetoothAlwaysUsageDescription`
- `NSCameraUsageDescription`
- `NSMicrophoneUsageDescription`
- notifications permission
- background modes тільки якщо реально треба і є виправданий UX

Архітектура Flutter:

```text
LooiBleClient
  scan/connect/disconnect
  handshake
  write/read/notify

LooiSession
  state machine: idle/scanning/connecting/handshaking/ready/reconnecting/error
  heartbeat loop 30ms
  battery poll 4s
  safety stop on disconnect

Controllers
  MotionController
  HeadController
  LightController
  SensorController
  GestureController(FE00 allowlist)

Agent Layer
  voice/camera/context -> intent -> robot tools
  tool calls: move, stop, head, light, gesture, ask_user, remember

UI
  face mode
  joystick/devtools
  sensor dashboard
  games
  settings/permissions
```

## OpenAI / AI design

Для "розумного" режиму я б не починав з повністю автономного агента. Краще 3 режими:

1. Manual mode: joystick + buttons + sensor dashboard.
2. Assisted mode: голосові команди, які перетворюються на tool calls.
3. Companion mode: камера/мікрофон/сенсори + personality + memory + обережні рухи.

OpenAI current docs підтримують:
- Realtime API для низької latency voice-to-voice, tool calls і session events.
- Responses API як unified endpoint для multimodal/text/image/tool workflows.
- Vision input для аналізу кадрів з камери.
- Function calling/tools, щоб модель не "вигадувала рух", а викликала `looi_move`, `looi_set_head`, `looi_set_light`, `looi_gesture`.

Практична схема:

```text
Flutter app
  BLE + camera + mic + face
  local safety rules
  sends events/tools to backend

Backend
  OpenAI Realtime/Responses
  tool policy
  memory
  user profile
  rate limits

Robot tools
  move(speed, turn, duration)
  stop()
  head(angle)
  light(brightness/pulse)
  gesture(name)
  describe_sensors()
```

Безпека:
- LLM не має отримувати raw arbitrary BLE write.
- Дати тільки high-level tools з hard limits: speed cap, duration cap, no movement if cliff unsafe, stop on connection loss.
- Emergency stop завжди локально, без мережі.

## Ідеї, які реально "зварганити"

### 1. Looi DevTools Pro

Мобільний додаток для дослідження:
- BLE scan/connect/init.
- Live GATT map.
- Raw write playground.
- Presets for `FED0/FED1/FED2/FE00`.
- FED9 decoder dashboard.
- CSV export logs.
- "Cliff mapping wizard": просить підняти перед/зад/ліво/право і сам будує таблицю.

Це найкращий перший проєкт, бо одразу дасть знання для всіх наступних.

### 2. Looi Remote + Tricks

Веселий RC:
- joystick;
- speed slider;
- head pitch slider;
- light brightness;
- drift mode;
- "trick buttons": nod, shake, quick back, spin, hello, scared jump;
- recorded macros: натиснув record, покатав, зберіг як gesture.

### 3. Desk Pet Companion

Телефон - обличчя, база - тіло:
- очі, рот, емоції, blinking, gaze tracking;
- LOOI рухається мікро-жестами під час відповіді;
- light pulses під TTS envelope;
- side touch = "погладити";
- cliff/contact = "ой, мене підняли".

Тут можна позичити ідеї з `haze_bot_app`.

### 4. Voice-Controlled Robot Butler

Команди:
- "підʼїдь сюди";
- "подивись вліво";
- "зроби сердечко";
- "нагадай мені через 20 хвилин";
- "що ти бачиш?";
- "де я поклав ключі?".

Камера телефону + vision memory: "запамʼятай, що ключі тут" -> зберегти кадр, опис і location label.

### 5. Looi Sensor Lab

Гра/лабораторія:
- live graphs для `FED9`;
- торкаєш боки - показує zones;
- нахиляєш - показує IMU;
- піднімаєш край - показує cliff;
- автоматично будує decoder.

### 6. Looi Party Games

Інтерактивні ігри:
- Simon Says: робот показує gesture, гравець повторює торканнями/нахилами.
- Emotion Guess: face app показує емоцію, треба вгадати.
- Hot/Cold Treasure: телефон бачить предмет, Looi світлом і рухом підказує.
- Desk Bowling: база штовхає легкі предмети, app веде рахунок.
- Dance Battle: музика -> beat detection -> рух/фари/голова.

### 7. Focus / Pomodoro Creature

Корисне:
- фокус таймер;
- Looi тихо "сидить";
- коли час перерви - підʼїжджає/світиться/киває;
- якщо телефон бачить, що тебе нема, ставить pause;
- якщо ти торкнувся боку, дає коротку verbal підтримку.

### 8. Home/Desk Notification Avatar

Інтеграції:
- календар;
- timer;
- GitHub/CI notifications;
- messages через desktop bridge;
- Looi показує тип події жестом: urgent = red blink + nod, success = spin, reminder = light pulse.

### 9. "Embodied ChatGPT"

Найамбітніше:
- realtime voice;
- camera vision;
- memory;
- robot tools;
- personality;
- local rules/reflexes;
- desktop backend для довгих задач.

Це схоже на `super-looi` + `ulooi`, але можна зробити Flutter-first.

## Рекомендований roadmap

### Phase 0 - стабілізувати Python

- Винести BLE протокол з `wasd.py` у маленький `looi_client.py`.
- Додати `set_motion`, `set_head`, `set_light`, `read_battery`, `subscribe_telemetry`.
- Додати telemetry logger для `FED9`.
- Додати safety: stop on exit/disconnect/exception.

### Phase 1 - Flutter DevTools

- Flutter app з BLE scan/connect/init.
- UI: status, battery, joystick, head slider, light slider.
- Log tab: FED5/FED9 hex.
- Export logs.

### Phase 2 - Sensor decoder

- Decode `FED9` packet types.
- Cliff lockout in UI.
- Touch events.
- IMU graph.
- Mapping wizard.

### Phase 3 - Face + robot body

- Full-screen robot face.
- TTS mouth sync.
- Light pulse sync.
- Head/motion gestures mapped to emotions.
- Local manual mode fallback.

### Phase 4 - AI assistant

- Backend with OpenAI Realtime/Responses.
- Function tools only, no raw BLE.
- Camera snapshot tool.
- Memory for object locations and preferences.
- Voice commands with confirmations for risky movement.

### Phase 5 - Mac/desktop bridge

- Local WebSocket bridge.
- Desktop notifications and files/tools.
- Robot as physical notification/assistant endpoint.

## Конкретно що я б зробив першим

1. Не починати одразу з великого AI companion.
2. Спочатку зробити Flutter `Looi DevTools`: це швидко дасть BLE стабільність і сенсорні дані.
3. Паралельно винести з `wasd.py` чистий Python SDK, щоб тестити без мобільної збірки.
4. Після цього зробити face mode на Flutter, позичивши патерни з `haze_bot_app`.
5. Тільки потім підключати OpenAI voice/vision і tool calls.

Мінімальний MVP, який уже буде вау:

```text
Flutter app:
  - fullscreen animated face
  - BLE connect to LOOI
  - joystick hidden in dev panel
  - robot reacts to touch/cliff
  - "say something" button
  - TTS + head/light gestures
  - 10 prebuilt tricks
```

Це дасть веселого desk pet без складної cloud-логіки. AI можна додати як другий шар.
