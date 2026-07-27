# h4xtor-share

`h4xtor-share` is an offline-first desktop app for transferring clipboard text and
arbitrary files directly between Windows, macOS and Linux devices.

The application does not require an account, cloud storage, a relay server or WAN
access. Peers discover each other with mDNS and communicate directly over the local
link.

## Current release: 0.1.0

The first release implements the complete IP data path:

- automatic peer discovery over mDNS;
- manual IP connection when multicast is blocked;
- six-digit out-of-band device pairing;
- TLS with certificate fingerprint pinning after pairing;
- push-based cross-device text clipboard;
- byte-streamed file transfer;
- resumable partial uploads;
- arbitrary file names and file types;
- no application-defined file-size limit;
- Windows, macOS and Linux packaging in GitHub Actions;
- operation without WAN access.

Actual limits are imposed by the receiving filesystem, free disk space, operating
system and transport. "Unlimited" does not mean infinite storage.

## Transport matrix

| Transport | Windows | macOS | Linux | Status |
|---|---:|---:|---:|---|
| Ethernet LAN | Yes | Yes | Yes | Implemented |
| Infrastructure Wi-Fi | Yes | Yes | Yes | Implemented |
| Existing hotspot link | Yes | Yes | Yes | Implemented |
| Existing Wi-Fi Direct IP link | Yes | Limited by macOS | Yes | Data path implemented; OS provisions the group |
| Bluetooth discovery | Experimental | Experimental | Experimental | Optional `bleak` dependency |
| Bluetooth bulk transfer | No | No | No | Native peripheral backends required |

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

## Development

Python 3.11 or later is required.

```bash
python -m venv .venv
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
   hotspot or OS-created Wi-Fi Direct group.
2. Select the other device. Use **Add IP** if multicast discovery is unavailable.
3. Click **Pair**.
4. Read the six-digit code on the receiver and enter it on the sender.
5. Select **Send clipboard** or **Send files**.

Received files are stored in the configured incoming directory. Transfers stream
directly to disk and can resume from an existing partial file.

## Repository layout

```text
src/h4xtor_share/
  app.py          Desktop UI and lifecycle
  client.py       Outbound pairing and transfer client
  config.py       Local identity and trust store
  crypto.py       Certificate creation and TLS setup
  discovery.py    mDNS service discovery
  models.py       Shared event and peer models
  server.py       Receiving API and streamed uploads
  transports.py   Platform transport capability reporting
tests/
  test_core.py
```

## Roadmap

- WinRT Bluetooth RFCOMM/GATT peripheral backend.
- macOS IOBluetooth peripheral backend.
- Linux BlueZ D-Bus/RFCOMM backend.
- In-app Windows and Linux Wi-Fi Direct group provisioning.
- Directory transfer manifests.
- Optional clipboard history with explicit retention controls.
