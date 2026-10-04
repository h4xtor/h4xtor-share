from __future__ import annotations

import socket
import time
from pathlib import Path

from h4xtor_share import integration


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_second_launch_hands_files_to_running_instance(tmp_path: Path) -> None:
    received: list[dict] = []
    port = free_port()
    server = integration.InstanceServer(tmp_path, port, received.append)
    assert server.start()
    try:
        message = {"cmd": "send", "paths": [str(tmp_path / "a.txt")]}
        assert integration.send_to_running_instance(tmp_path, port, message)
        deadline = time.monotonic() + 3
        while not received and time.monotonic() < deadline:
            time.sleep(0.05)
        assert received and received[0]["paths"] == message["paths"]
    finally:
        server.stop()
    assert not integration.send_to_running_instance(tmp_path, port, {"cmd": "show"})


def test_launches_during_startup_are_held_until_the_app_is_ready(tmp_path: Path) -> None:
    """Explorer starts one process per selected file; the first claims the port early."""
    port = free_port()
    server = integration.InstanceServer(tmp_path, port)
    assert server.start()
    try:
        first = {"cmd": "send", "paths": ["a.txt"]}
        assert integration.send_to_running_instance(tmp_path, port, first)
        time.sleep(0.3)
        received: list[dict] = []
        server.set_handler(received.append)
        second = {"cmd": "send", "paths": ["b.txt"]}
        assert integration.send_to_running_instance(tmp_path, port, second)
        deadline = time.monotonic() + 3
        while len(received) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert [m["paths"] for m in received] == [["a.txt"], ["b.txt"]]
    finally:
        server.stop()


def test_wrong_token_is_ignored(tmp_path: Path) -> None:
    received: list[dict] = []
    port = free_port()
    server = integration.InstanceServer(tmp_path, port, received.append)
    assert server.start()
    try:
        (tmp_path / "instance.token").write_text("forged", encoding="utf-8")
        assert not integration.send_to_running_instance(tmp_path, port, {"cmd": "show"})
        assert not received
    finally:
        server.stop()


def test_launch_command_points_at_this_package() -> None:
    command = integration.launch_command()
    assert command
    assert command[-1] == "h4xtor_share" or command[0].endswith(".exe")
