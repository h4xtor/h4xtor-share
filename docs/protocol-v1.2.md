# Protocol additions in v1.2 (Join parity)

All new endpoints use the existing v1 transport: HTTPS on port 47474, pinned TLS,
`Authorization: Bearer <token>` + `X-H4xtor-Device: <device_id>` checked by the existing
`authenticate()` on both sides. JSON bodies, UTF-8. Errors are plain-text bodies with a
human-readable Danish or English reason (the desktop shows them as-is).

A sender only calls an endpoint when the receiver advertises the capability (from `/info`,
pairing response, mDNS/UDP). Older peers never see the new calls.

## Capabilities

| Side | New capability | Meaning |
|------|----------------|---------|
| Desktop | `notifications` | Accepts `POST /api/v1/notification` |
| Desktop | `sms` | Accepts `POST /api/v1/sms/incoming` |
| Android | `notifications` | Pushes notifications; accepts `POST /api/v1/notification/action` |
| Android | `sms` | Accepts the `/api/v1/sms/*` calls below |
| Android | `screenshot-request` | Accepts `POST /api/v1/screenshot` |
| Android | `find-phone` | Accepts `POST /api/v1/find` |
| Android | `remote-control` | Accepts `/api/v1/remote/volume`, `/speak`, `/wallpaper` |

Android advertises these always (the feature exists); when the user has switched a feature
off on the phone the endpoint answers **403** with a reason such as
`"SMS er slået fra på telefonen."`.

## Phone → PC (desktop server)

### `POST /api/v1/notification`
```json
{"event": "posted", "key": "0|com.whatsapp|1|null|10123", "package": "com.whatsapp",
 "app": "WhatsApp", "title": "Mor", "text": "Kommer du til middag?", "time": 1760090000000,
 "icon": "<base64 PNG, max 48 KB, may be empty>", "can_reply": true, "can_dismiss": true}
```
```json
{"event": "removed", "key": "0|com.whatsapp|1|null|10123"}
```
Limits: key ≤ 512, package ≤ 200, app ≤ 80, title ≤ 200, text ≤ 4000 (clip, do not reject),
icon ≤ 64 KB base64 (drop if larger or invalid). Unknown `event` → 400.
Response `{"accepted": true}`.

### `POST /api/v1/sms/incoming`
```json
{"thread_id": "12", "address": "+4512345678", "name": "Mor", "body": "Hej", "time": 1760090000000}
```
Response `{"accepted": true}`. `body` ≤ 4000, `address` ≤ 64, `name` ≤ 80.

## PC → phone (Android server)

| Call | Body | Response |
|------|------|----------|
| `POST /api/v1/notification/action` | `{"key": "...", "action": "reply"\|"dismiss", "text": "..."}` | `{"ok": true}`; 404 unknown key; 400 no reply possible |
| `POST /api/v1/sms/threads` | `{"limit": 50}` | `{"threads": [{"thread_id","address","name","snippet","time","unread"}]}` newest first |
| `POST /api/v1/sms/messages` | `{"thread_id": "12", "limit": 100}` | `{"messages": [{"id","address","body","time","outgoing"}]}` oldest first |
| `POST /api/v1/sms/send` | `{"address": "+45…", "text": "…"}` | `{"ok": true}` (multipart SMS for long text) |
| `POST /api/v1/screenshot` | `{}` | `{"accepted": true}` – the phone asks the user for screen-capture consent, captures one frame and sends it back to the **requesting** PC with the normal `/api/v1/files` upload, named `Skaermbillede-YYYYMMDD-HHMMSS.png` |
| `POST /api/v1/find` | `{"action": "start"\|"stop"}` | `{"ringing": true\|false}` – loud alarm (alarm stream, max volume, works on silent) + vibration until stopped on the phone or by `stop` |
| `POST /api/v1/remote/volume` | `{"level": 0-100}` | `{"level": 0-100}` (media volume) |
| `POST /api/v1/remote/speak` | `{"text": "…"}` (≤ 1000 chars) | `{"ok": true}` (text-to-speech) |
| `PUT /api/v1/remote/wallpaper` | raw image bytes, `Content-Length` ≤ 20 MB | `{"ok": true}` |

`time` values are milliseconds since the Unix epoch.

## Chrome extension ↔ desktop (loopback API, 127.0.0.1:47476)

`POST /v1/send-all` `{"kind": "link"|"text"|"file-url", "value": "…"}` →
`{"results": [{"id": "…", "name": "…", "ok": true, "error": ""}, …]}` – sends to every paired
device in parallel. 404 when there are no paired devices.
