# h4xtor-share

`h4xtor-share` is an offline-first app for transferring clipboard text and arbitrary
files directly between Windows, macOS, Linux and Android devices.

The application does not require an account, cloud storage, a relay server or WAN
access. Peers discover each other with mDNS and communicate directly over the local
link.

## Current release: 0.2.0

Version 0.2.0 adds the cross-platform UI and Android client/server:

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
5. Select **Send clipboard** or **Send files**, or drop files onto the desktop drop
   zone. Follow active transfers in the **Transfers** tab.

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
  models.py       Shared event and peer models
  scanner.py      Concurrent local-network peer scan
  server.py       Receiving API and streamed uploads
  transports.py   Platform transport capability reporting
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
- Directory transfer manifests.
- Optional clipboard history with explicit retention controls.
