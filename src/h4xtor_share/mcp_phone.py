"""Let an AI see and steer the phone: a tiny MCP server (stdio, JSON-RPC 2.0).

An AI app (Claude Desktop, Claude Code …) starts ``h4xtor-share --mcp`` and gets the tools
below. They go through the desktop app's loopback API, so everything stays on this PC:

* the user approves the AI once in h4xtor share ("Tillad") and must switch on
  "Lad en AI styre telefonen";
* the phone asks before it shares its screen and keeps a notification up meanwhile.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from h4xtor_share import __version__
from h4xtor_share.config import Config
from h4xtor_share.local_api import LOCAL_API_PORT_OFFSET

PROTOCOL = "2025-06-18"
WAIT_FOR_START = 60  # seconds for the user to tap "Start nu" on the phone

_POINT = {"x": {"type": "number"}, "y": {"type": "number"}}
_DEVICE = {"device_id": {"type": "string", "description": "From phone_list; default: the phone"}}
TOOLS: list[dict[str, Any]] = [
    {"name": "phone_list", "description": "The paired devices (id, name, platform, online).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "phone_screen",
     "description": "A screenshot of the phone. The first time the user must tap 'Start nu' "
                    "on the phone. Coordinates in the other tools are pixels of this picture.",
     "inputSchema": {"type": "object", "properties": {**_DEVICE}}},
    {"name": "phone_tap", "description": "Tap at x, y (pixels of the last screenshot). "
                                         "Returns the new screen.",
     "inputSchema": {"type": "object", "properties": {**_POINT, **_DEVICE},
                     "required": ["x", "y"]}},
    {"name": "phone_swipe",
     "description": "Swipe from x, y to x2, y2 (pixels of the last screenshot), e.g. to scroll. "
                    "Returns the new screen.",
     "inputSchema": {"type": "object", "properties": {
         **_POINT, "x2": {"type": "number"}, "y2": {"type": "number"},
         "ms": {"type": "integer", "description": "Duration, default 300"}, **_DEVICE},
         "required": ["x", "y", "x2", "y2"]}},
    {"name": "phone_type", "description": "Type text into the focused text field. "
                                          "Returns the new screen.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, **_DEVICE},
                     "required": ["text"]}},
    {"name": "phone_button", "description": "Press back, home or recents. Returns the new screen.",
     "inputSchema": {"type": "object", "properties": {
         "button": {"type": "string", "enum": ["back", "home", "recents"]}, **_DEVICE},
         "required": ["button"]}},
    {"name": "phone_stop", "description": "Stop sharing the phone's screen.",
     "inputSchema": {"type": "object", "properties": {**_DEVICE}}},
]


class ToolError(Exception):
    """Shown to the AI as the tool's answer (isError)."""


class PhoneBridge:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.base = f"http://127.0.0.1:{self.config.port + LOCAL_API_PORT_OFFSET}"
        self.token_path = self.config.path.parent / "ai-mcp.token"
        self.started: set[str] = set()
        self.seq: dict[str, int] = {}
        self.size: dict[str, tuple[int, int]] = {}

    # ------------------------------------------------------------ the local API
    def _call(self, method: str, path: str, body: dict[str, Any] | None = None,
              timeout: float = 15) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data, headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            if error.code == 401 and path != "/v1/connect":
                self._connect()
                return self._call(method, path, body, timeout)
            raise ToolError(error.read().decode("utf-8", "replace") or str(error)) from error
        except OSError as error:
            raise ToolError("h4xtor share kører ikke på denne PC. Start appen og prøv igen.") \
                from error

    def _token(self) -> str:
        try:
            return self.token_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def _connect(self) -> None:
        """Ask the user once in the desktop app; the token is kept for next time."""
        self.token_path.unlink(missing_ok=True)
        answer = self._call("POST", "/v1/connect", {"name": "AI (MCP)"}, timeout=130)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(answer["token"], encoding="utf-8")

    # ------------------------------------------------------------------- phone
    def devices(self) -> list[dict[str, Any]]:
        return list(self._call("GET", "/v1/devices")["devices"])

    def _device(self, args: dict[str, Any]) -> str:
        if args.get("device_id"):
            return str(args["device_id"])
        phones = [d for d in self.devices() if d.get("platform") == "android"]
        phones.sort(key=lambda d: not d.get("online"))  # keeps the app's own order otherwise
        if not phones:
            raise ToolError("Ingen parret Android-telefon. Par telefonen med h4xtor share først.")
        return str(phones[0]["id"])

    def _phone(self, device: str, op: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._call("POST", f"/v1/phone/{op}", {"device_id": device, **(body or {})})

    def screen(self, device: str) -> dict[str, Any]:
        """The newest frame (newer than the last one this AI saw), starting sharing if needed."""
        if device not in self.started:
            self._phone(device, "start")
            self.started.add(device)
            self.seq[device] = 0
        deadline = time.monotonic() + WAIT_FOR_START
        restarted = False
        while True:
            frame = self._phone(device, "screen", {"after": self.seq.get(device, 0)})
            if frame.get("active") and frame.get("image"):
                self.seq[device] = int(frame.get("seq", 0))
                self.size[device] = (int(frame.get("width", 0)), int(frame.get("height", 0)))
                return frame
            if not frame.get("active") and not frame.get("waiting"):
                if restarted:  # the user stopped it on the phone
                    self.started.discard(device)
                    raise ToolError("Skærmdelingen blev stoppet på telefonen.")
                self._phone(device, "start")
                self.seq[device] = 0
                restarted = True
            if time.monotonic() > deadline:
                raise ToolError("Telefonen delte ikke skærmen. Tryk \"Start nu\" på telefonen "
                                "(og slå \"Vis og styr skærmen fra PC'en\" til i telefonens app).")
            time.sleep(0.3)

    def act(self, device: str, action: dict[str, Any]) -> None:
        self._phone(device, "input", {"action": action})

    def fraction(self, device: str, x: float, y: float) -> tuple[float, float]:
        if device not in self.size:
            self.screen(device)
        width, height = self.size[device]
        return min(1.0, max(0.0, x / max(1, width))), min(1.0, max(0.0, y / max(1, height)))

    # ------------------------------------------------------------------- tools
    def run(self, name: str, args: dict[str, Any]) -> list[dict[str, Any]]:
        if name == "phone_list":
            return [_text(json.dumps(self.devices(), ensure_ascii=False))]
        device = self._device(args)
        if name == "phone_stop":
            self._phone(device, "stop")
            self.started.discard(device)
            return [_text("Stoppet.")]
        if name == "phone_tap":
            x, y = self.fraction(device, float(args["x"]), float(args["y"]))
            self.act(device, {"type": "tap", "x": x, "y": y})
        elif name == "phone_swipe":
            x, y = self.fraction(device, float(args["x"]), float(args["y"]))
            x2, y2 = self.fraction(device, float(args["x2"]), float(args["y2"]))
            ms = int(min(3000, max(80, int(args.get("ms") or 300))))
            self.act(device, {"type": "swipe", "x": x, "y": y, "x2": x2, "y2": y2, "ms": ms})
        elif name == "phone_type":
            self.act(device, {"type": "text", "text": str(args["text"])})
        elif name == "phone_button":
            if args.get("button") not in {"back", "home", "recents"}:
                raise ToolError("button must be back, home or recents.")
            self.act(device, {"type": args["button"]})
        elif name != "phone_screen":
            raise ToolError(f"Unknown tool {name}.")
        if name != "phone_screen":
            time.sleep(0.6)  # let the phone draw the result before looking
        frame = self.screen(device)
        width, height = self.size[device]
        return [
            {"type": "image", "data": frame["image"],
             "mimeType": "image/png" if frame.get("format") == "png" else "image/jpeg"},
            _text(f"Skærmbillede {width}x{height} pixels."),
        ]


def _text(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def handle(bridge: PhoneBridge, message: dict[str, Any]) -> dict[str, Any] | None:
    """One JSON-RPC message in, its answer out (None for notifications)."""
    method, params, ident = message.get("method"), message.get("params") or {}, message.get("id")
    if ident is None:
        return None
    if method == "initialize":
        result: dict[str, Any] = {
            "protocolVersion": params.get("protocolVersion") or PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "h4xtor-share-phone", "version": __version__},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            result = {"content": bridge.run(str(params.get("name")),
                                            dict(params.get("arguments") or {}))}
        except (ToolError, KeyError, ValueError) as error:
            result = {"content": [_text(str(error))], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": ident,
                "error": {"code": -32601, "message": f"Unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(bridge: PhoneBridge | None = None) -> None:
    # shortcut: needs the AI app to hand us stdin/stdout pipes (all MCP clients do).
    bridge = bridge or PhoneBridge()
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            answer = handle(bridge, json.loads(line))
        except ValueError:
            answer = {"jsonrpc": "2.0", "id": None,
                      "error": {"code": -32700, "message": "Parse error"}}
        if answer is not None:
            sys.stdout.write(json.dumps(answer) + "\n")
            sys.stdout.flush()


def setup_json() -> str:
    """What the user pastes into the AI app's MCP settings."""
    from h4xtor_share.integration import launch_command

    command = launch_command()
    if command[0].lower().endswith("pythonw.exe"):  # the AI needs a console Python for pipes
        command[0] = command[0][: -len("pythonw.exe")] + "python.exe"
    server = {"command": command[0], "args": [*command[1:], "--mcp"]}
    return json.dumps({"mcpServers": {"h4xtor-phone": server}}, indent=2)


if __name__ == "__main__":
    serve()
