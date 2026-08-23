# h4xtor-share

`h4xtor-share` is an offline-first app for transferring clipboard text and arbitrary
files directly between Windows, macOS, Linux and Android devices.

The application does not require an account, cloud storage, a relay server or WAN
access. Peers discover each other with mDNS and communicate directly over the local
link.

## Current release: 0.4.0

Version 0.4.0 turns transfers into a first-class, live, resumable experience and adds directory transfer:

- **directory transfer**: send a whole folder tree; the receiver recreates the
  exact relative layout with an atomic completion step and collision-free names;
- **live transfer speed and percentage**: the Transfers tab now shows an
  explicit 0-100% progress value plus a smoothed MB/s throughput for every
  active send and receive;
- **automatic resume**: an interrupted file transfer is retried from the exact
  byte the receiver already holds instead of restarting — no user action needed;
- **parallel sends**: multiple files are streamed concurrently (bounded) to
  better saturate fast local links;
- **UDP broadcast discovery**: a zero-configuration UDP announce/listen fallback
  keeps automatic discovery working even on networks that block mDNS multicast;
- **capability negotiation**: devices advertise what they support
  (`clipboard`, `files`, `resume`, `folders`) over mDNS, UDP and the info
  endpoint, so newer features are only offered to peers that understand them;
- everything from 0.3.0 remains: mDNS discovery, LAN scanning, manual IP,
  six-digit pairing, pinned TLS, clipboard sync, history dashboard and
  streaming transfers without a size limit.

### Version 0.3.0

Version 0.3.0 added a UI/UX overhaul, direct file execution, universal
clipboard sync and a full history dashboard:

- redesigned dark UI with prominent **Connect** buttons for device pairing;
- **connection status LEDs** per device (green online / yellow paired / red offline);
- **signal strength** bars computed from live ping round-trip time;
- smooth real-time **progress bars** for every active file transfer;
- **direct file execution** from the UI: Windows `startfile`, Android APK
  install and `ACTION_VIEW` intents, Linux `chmod +x` + `xdg-open`;
- **universal clipboard sync**: text copied on any running connected device is
  broadcast to every paired device (echo-protected on both platforms);
- **history dashboard** tracking sent files/links, received files/links and
  connected devices (IP, OS, name, first/last seen, connection count);
- everything from 0.2.0 remains: mDNS discovery, LAN scanning, manual IP,
  six-digit pairing, pinned TLS, streaming transfers without a size limit.

### Version 0.2.0

Version 0.2.0 added the cross-platform UI and Android client/server:

- automatic peer discovery over mDNS;
- active LAN scanning when mDNS is blocked;
- manual IP connection when multicast is blocked;
- six-digit out-of-band device pairing;
- TLS with certificate fingerprint pinning after pairing;
- push-based cross-device text clipboard;
- byte-streamed file transfer;
- desktop drag-and-drop file sending;
- live inbound and outbound transfer progress;
- arbitrary file names and file types;
- no application-defined file-size limit;
- native Android send, receive, discovery and pairing;
- Windows, macOS, Linux and Android packaging in GitHub Actions;
- operation without WAN access.

Actual limits are imposed by the receiving filesystem, free disk space, operating
system and transport. "Unlimited" does not mean infinite storage.

File contents are transferred as a raw byte stream, so every file type works.
Received names are sanitized to stay valid on all three operating systems:
characters that Windows reserves (`< > : " | ? *`) are removed, reserved device
names (`CON`, `COM1`, `NUL`, ...) get a leading underscore, and a file that
already exists is stored under a numbered variant instead of being overwritten.

The Linux release artifact is built on Ubuntu 22.04 for wider glibc compatibility.
The source package remains the portable fallback for other distributions.

## Transport matrix

| Transport | Windows | macOS | Linux | Android | Status |
|---|---:|---:|---:|---:|---|
| Ethernet LAN | Yes | Yes | Yes | Yes | Implemented |
| Infrastructure Wi-Fi | Yes | Yes | Yes | Yes | Implemented |
| Existing hotspot link | Yes | Yes | Yes | Yes | Implemented |
| Existing Wi-Fi Direct IP link | Yes | Limited by macOS | Yes | Yes | Data path implemented; OS provisions the group |
| Bluetooth discovery | Experimental | Experimental | Experimental | No | Optional desktop `bleak` dependency |
| Bluetooth bulk transfer | No | No | No | No | Native peripheral backends required |

The table is deliberately strict. macOS does not expose a general-purpose public
Wi-Fi Direct provisioning API comparable to Windows WiFiDirect or Linux
`wpa_supplicant` P2P. The application can transfer over any IP link the OS exposes,
including a pre-established Wi-Fi Direct group or hotspot.

Bluetooth bulk transfer is not falsely presented as complete. Cross-platform
Bluetooth requires separate native peripheral/server implementations for WinRT,
IOBluetooth and BlueZ. The core transfer protocol is transport-independent so those
adapters can be added without changing pairing, clipboard or file semantics.

## Security model

1. Every installation generates its own RSA key and self-signed TLS certificate.
2. The receiving device displays a random six-digit code for two minutes.
3. The sending user enters that code on the sending device.
4. The peer stores a bearer token and pins the receiver certificate fingerprint.
5. Later transfers reject changed certificates and invalid tokens.

Pairing grants one direction of transfer. Pair both directions if both devices should
be allowed to send.

Incoming paths are sanitized and files are written to a random `.part` path before an
atomic rename. Existing files are never overwritten.

## Technical design

### Automatic LAN discovery

Discovery is layered so that devices on the same subnet find each other with no
configuration, even when individual mechanisms are blocked:

1. **mDNS / DNS-SD** is the primary path. The desktop app registers a
   `_h4xtor-share._tcp.local.` service (via the `zeroconf` library) advertising
   the device id, display name, TLS fingerprint, platform and capability set as
   TXT records, and browses the same type to learn about peers. Android uses the
   platform `NsdManager` service for an equivalent announcement and browse. mDNS
   is true zero-configuration: it requires no server, no address list and no
   user action, and it carries the fingerprint inline so pairing can pin the
   correct certificate before the first connection.

2. **UDP broadcast discovery** is a fallback for networks that filter
   multicast. Every device periodically (every 5 seconds, plus an immediate
   announce on startup) broadcasts a small JSON announcement — protocol version,
   device id, name, platform, port, fingerprint and capabilities — to UDP port
   47474 on `255.255.255.255` and to each interface address. A listener binds
   the same UDP port (UDP and TCP share port numbers freely), validates the
   protocol version, drops its own announcements by device id and reports the
   rest as peers. Broadcast is usually forwarded within a subnet even when
   multicast is not, which makes this a cheap, robust complement to mDNS.

3. **Active LAN scanning** probes each host in the local `/24` (configurable
   CIDR, capped at 1024 hosts) with a bounded-concurrency TLS `GET
   /api/v1/info` and a 750 ms timeout. A host is only accepted when it answers
   with a protocol-compatible info payload, so the scan never mistakes unrelated
   services for peers. The desktop scanner uses 64 concurrent probes; the
   Android one uses a 48-thread executor.

4. **Manual IP** remains available when the network isolates devices entirely
   (guest Wi-Fi with client isolation, VPNs, routed subnets).

All discovered peers are unified into the same `Peer` model (id, name, address,
port, fingerprint, platform, transport, capabilities), so a device discovered by
any mechanism can be used identically as sender and receiver.

### Chunked file transfer and live status

Transfers are HTTP over TLS with certificate-fingerprint pinning, chunked into
1 MiB buffers, and streamed directly to disk — never buffered whole in memory.

1. **Pairing** runs once per direction. The receiver generates a six-digit code
   (120-second TTL) on `POST /api/v1/pair/request`; the sender confirms it on
   `POST /api/v1/pair/confirm` and receives a bearer token plus the certificate
   fingerprint. The receiver stores an inbound token, the sender stores the
   outbound token and pins the fingerprint. Later transfers authenticate with
   `Authorization: Bearer <token>` + `X-H4xtor-Device` and reject any TLS
   handshake whose certificate fingerprint differs — a changed certificate
   invalidates the pairing.

2. **File transfer** is two-phase. `POST /api/v1/files/init` declares the
   transfer id (a 32-hex random UUID), sanitized file name and byte size; the
   receiver replies with the current resume offset (the size of any existing
   `.h4xtor-<id>.part` file). The sender then streams the remaining bytes with
   `PUT /api/v1/files/<id>` using `X-H4xtor-Offset` for the start position. The
   receiver appends each 1 MiB chunk to the `.part` file, emits a progress
   event, and on the final byte atomically renames the part to its final,
   collision-free destination.

3. **Directory transfer** extends the same model with a manifest. `POST
   /api/v1/folders/init` carries the folder name plus one entry per file (its
   own transfer id, sanitized relative path and size). The receiver creates an
   isolated `.h4xtor-folder-<id>/` staging directory and returns per-file resume
   offsets. Files are streamed with `PUT /api/v1/folders/<folder>/<file>` into
   the staging tree, and each completed part is renamed to its relative path.
   Only when every entry has arrived does `POST /api/v1/folders/complete`
   atomically promote the staging directory to the final, collision-free folder
   name. A partial folder is left in place so the sender can retry and resume.
   Every relative path is sanitized segment-by-segment, neutralizing `../`
   traversal, absolute paths and Windows-reserved names.

4. **Live status** flows in both directions. Each chunk triggers a
   `TransferProgress` event (transfer id, file name, bytes sent, total, send or
   receive direction) from the async core into the UI event queue. The desktop
   Transfers tab renders an explicit 0-100% value, a smooth progress bar and a
   smoothed MB/s figure computed from the delta between successive events
   (exponentially weighted average). Android renders the same percentage in its
   status line.

5. **Resume** is automatic. The client keeps the transfer id of any interrupted
   send per (peer, file) in memory, so a retry reuses it and the receiver's
   init response tells the sender exactly where to continue. Stale `.part`
   files and staging directories older than 24 hours are swept on server start.

### Optimized for local network speed

- **1 MiB chunk size and blocking-free I/O**: reads happen in a worker thread
  (`asyncio.to_thread`) and writes are async, so the event loop never blocks on
  disk and throughput is bounded by the network, not the filesystem.
- **Streaming, not buffering**: the HTTP client streams chunk by chunk and the
  server writes chunk by chunk; a multi-gigabyte file never enters memory.
- **Reused HTTP sessions and keep-alive**: the init and upload requests share
  one `aiohttp.ClientSession`, avoiding per-request TLS handshakes (the TLS
  handshake, not the wire, is the dominant latency cost on a fast LAN).
- **Bounded concurrency**: multiple files (and folder entries) stream in
  parallel — 3 concurrent sends on the desktop client, 4 concurrent folder
  entries — saturating the link with many small files while staying gentle on
  receivers.
- **Per-peer session pooling on the server**: `aiohttp`'s runner handles
  concurrent uploads with a single TLS context, and the Android server uses a
  cached thread pool with a 1 MiB copy buffer.
- **No application-imposed size limit**: `client_max_size=0` on the server and
  `ClientTimeout(total=None)` on large transfers mean the only limits are the
  receiving filesystem and free disk space.

## Installing

### Windows

The easiest path is the single-file executable. Download
`h4xtor-share-windows.exe` from the [latest release](https://github.com/h4xtor/h4xtor-share/releases/latest)
and run it. No Python or other dependency is required.

To install through Python instead (needs Python 3.11 or later, tick
"Add python.exe to PATH" during setup), open PowerShell and run:

```powershell
irm https://raw.githubusercontent.com/h4xtor/h4xtor-share/main/scripts/install.ps1 | iex
```

This installs into an isolated virtual environment, creates a Start Menu and
desktop shortcut, and re-running it upgrades the app.

### Linux

The standalone executable is built on Ubuntu 22.04. Alternatively install
through Python 3.11 or later (Debian/Ubuntu also need the Tk runtime):

```bash
sudo apt install python3-tk
bash <(curl -fsSL https://raw.githubusercontent.com/h4xtor/h4xtor-share/main/scripts/install.sh)
```

The script creates `~/.local/bin/h4xtor-share` as the launcher.

### macOS

Download `h4xtor-share-macos` from the [latest release](https://github.com/h4xtor/h4xtor-share/releases/latest),
or install through Python 3.11 or later:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/h4xtor/h4xtor-share/main/scripts/install.sh)
```

Both install scripts download the release wheel from GitHub and fall back to
installing directly from the repository when no release is available yet.

### Android

Download `h4xtor-share-android.apk` from the
[latest release](https://github.com/h4xtor/h4xtor-share/releases/latest), allow
installation from the browser or file manager when Android prompts, and install it.
The app requires Android 10 or later and saves received files in Downloads.

## Building a release

Push a `v*` tag and GitHub Actions builds the Windows, macOS and Linux
executables, an installable Android APK, and the Python wheel and attaches them
to the release:

```bash
git tag v0.2.0
git push origin v0.2.0
```

## Development

Python 3.11 or later is required.

```bash
python -m venv .venv
```

Linux also requires the Tk runtime used by the desktop interface:

```bash
# Debian, Ubuntu and Kali
sudo apt install python3-tk

# Fedora and RHEL
sudo dnf install python3-tkinter
```

Activate the environment, then install and run:

```bash
python -m pip install -e ".[dev]"
python -m h4xtor_share
```

Run validation:

```bash
ruff check .
pytest
```

## Using the app

1. Start `h4xtor-share` on two devices connected through the same LAN, Wi-Fi,
   hotspot or OS-created Wi-Fi Direct group. On Windows, allow the app through
   the firewall when prompted so peers can reach it.
2. Select the other device. Use **Scan LAN** or **Add IP** if multicast discovery
   is unavailable.
3. Click **Pair**.
4. Read the six-digit code on the receiver and enter it on the sender.
5. Select **Send clipboard**, **Send files** or **Send folder**, or drop files
   and folders onto the desktop drop zone. Follow active transfers — including
   live 0-100% progress, percentage and MB/s speed — in the **Transfers** tab.
   An interrupted file transfer resumes automatically when you send it again.
6. Received files and folders can be opened or revealed from the **History**
   tab. On Android, received APKs offer a direct install action.
7. Copy text on any paired device to have it appear on every other running,
   connected device (disable in Settings if you do not want automatic sync).

Received files are stored in the configured incoming directory. Transfers stream
directly to disk without loading the complete file into memory.

## Repository layout

```text
src/h4xtor_share/
  app.py          Desktop UI and lifecycle
  client.py       Outbound pairing and transfer client
  config.py       Local identity and trust store
  crypto.py       Certificate creation and TLS setup
  discovery.py    mDNS service discovery
  history.py      Bounded JSON history of transfers, links and devices
  models.py       Shared event and peer models
  openers.py      Cross-platform open/execute for received files
  scanner.py      Concurrent local-network peer scan
  server.py       Receiving API and streamed uploads
  transports.py   Platform transport capability reporting
  udp.py          UDP broadcast discovery fallback
packaging/
  h4xtor-share.spec   PyInstaller build specification
  make_icon.py        Icon generator (pure stdlib)
scripts/
  install.ps1         Windows installer (Python/pip)
  install.sh          Linux and macOS installer (Python/pip)
tests/
  test_core.py
  test_scanner.py
android/
  app/             Native Android client/server application
```

## Roadmap

- WinRT Bluetooth RFCOMM/GATT peripheral backend.
- macOS IOBluetooth peripheral backend.
- Linux BlueZ D-Bus/RFCOMM backend.
- In-app Windows and Linux Wi-Fi Direct group provisioning.
- Directory transfer on Android (the Android client currently shares files and
  clipboard; the desktop folder-transfer protocol is capability-negotiated so
  folder sends are only offered to peers that support them).
- Clipboard history with explicit retention controls.
