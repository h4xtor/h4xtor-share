import asyncio
import base64

import pytest

from h4xtor_share.mirror_window import gesture, wheel


def test_a_short_press_is_a_tap_and_a_drag_a_swipe() -> None:
    assert gesture((180, 320), (183, 322), 0.1, (360, 640)) == {"type": "tap", "x": 0.5, "y": 0.5}
    swipe = gesture((180, 500), (180, 100), 0.4, (360, 640))
    assert swipe["type"] == "swipe" and swipe["y"] > swipe["y2"] and swipe["ms"] == 400
    assert gesture((0, 0), (900, -50), 9, (360, 640))["x2"] == 1.0  # dragged off the picture
    assert gesture((0, 0), (900, -50), 9, (360, 640))["ms"] == 3000
    down, up = wheel(-120), wheel(120)
    assert down["y"] > down["y2"] and up["y"] < up["y2"]  # rolling down moves the finger up


def test_window_shows_frames_and_turns_clicks_into_taps(tmp_path) -> None:
    import tkinter as tk
    import types

    from h4xtor_share.mirror_window import MirrorWindow
    from h4xtor_share.models import Peer
    from h4xtor_share.ui_kit import Theme

    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}".splitlines()[0])
    loop = asyncio.new_event_loop()
    import threading

    threading.Thread(target=loop.run_forever, daemon=True).start()
    picture = tk.PhotoImage(master=root, width=90, height=160)
    picture.put("#3366cc", to=(0, 0, 90, 160))
    picture.write(str(tmp_path / "frame.png"), format="png")
    png = (tmp_path / "frame.png").read_bytes()
    calls: list[tuple[str, object]] = []

    async def start(peer, fmt):
        calls.append(("start", fmt))
        return {"accepted": True}

    async def frame(peer, after):
        await asyncio.sleep(0.05)
        return {"active": True, "seq": 1, "width": 90, "height": 160, "format": "png",
                "image": base64.b64encode(png).decode()}

    async def send(peer, action):
        calls.append(("input", action))

    async def stop(peer):
        calls.append(("stop", None))

    client = types.SimpleNamespace(mirror_start=start, mirror_frame=frame, mirror_input=send,
                                   mirror_stop=stop)
    app = types.SimpleNamespace(theme=Theme(root, dark=True), client=client,
                                runtime=types.SimpleNamespace(loop=loop))
    root.theme, root.client, root.runtime = app.theme, client, app.runtime
    peer = Peer("ab" * 16, "Pixel", "192.168.1.5", 47474, "cd" * 32, "android",
                capabilities=("screen-mirror",))
    try:
        window = MirrorWindow(root, peer)
        import time

        deadline = time.time() + 5
        while window.size == (0, 0) and time.time() < deadline:
            root.update()
            time.sleep(0.02)
        assert window.size == (90, 160)  # the picture is on screen
        window._down(types.SimpleNamespace(x=45, y=40))
        window._up(types.SimpleNamespace(x=45, y=40))
        deadline = time.time() + 3
        while not any(kind == "input" for kind, _ in calls) and time.time() < deadline:
            root.update()
            time.sleep(0.02)
        assert ("input", {"type": "tap", "x": 0.5, "y": 0.25}) in calls
        window.close()
        time.sleep(0.2)
        assert ("stop", None) in calls
    finally:
        loop.call_soon_threadsafe(loop.stop)
        root.destroy()
