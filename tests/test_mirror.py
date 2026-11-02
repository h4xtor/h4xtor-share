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


def test_page_shows_frames_warns_without_control_and_turns_clicks_into_taps(tmp_path) -> None:
    import threading
    import time
    import tkinter as tk
    import types

    from h4xtor_share.mirror_window import MirrorView
    from h4xtor_share.models import Peer
    from h4xtor_share.ui_kit import Theme

    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}".splitlines()[0])
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    picture = tk.PhotoImage(master=root, width=90, height=160)
    picture.put("#3366cc", to=(0, 0, 90, 160))
    picture.write(str(tmp_path / "frame.png"), format="png")
    png = (tmp_path / "frame.png").read_bytes()
    calls: list[tuple[str, object]] = []

    async def start(peer, fmt):
        calls.append(("start", fmt))
        return {"accepted": True, "control": False}

    async def frame(peer, after):
        await asyncio.sleep(0.05)
        return {"active": True, "seq": 1, "width": 90, "height": 160, "format": "png",
                "control": False, "image": base64.b64encode(png).decode()}

    async def send(peer, action):
        calls.append(("input", action))

    async def stop(peer):
        calls.append(("stop", None))

    flags: dict[str, bool] = {}
    app = types.SimpleNamespace(
        theme=Theme(root, dark=True),
        client=types.SimpleNamespace(mirror_start=start, mirror_frame=frame, mirror_input=send,
                                     mirror_stop=stop),
        runtime=types.SimpleNamespace(loop=loop),
        config_store=types.SimpleNamespace(get_flag=lambda k, d=False: flags.get(k, d),
                                           set_flag=flags.__setitem__),
        _set_ai_control=lambda value: flags.__setitem__("ai_control", value),
    )
    peer = Peer("ab" * 16, "Pixel", "192.168.1.5", 47474, "cd" * 32, "android",
                capabilities=("screen-mirror",))

    def wait(condition) -> None:
        deadline = time.time() + 5
        while not condition() and time.time() < deadline:
            root.update()
            time.sleep(0.02)

    try:
        view = MirrorView(root, app)
        view.pack(fill="both", expand=True)
        view.show(peer, "Android · Online")
        assert view.name.cget("text") == "Pixel" and not view.running
        assert not view.warning.winfo_manager()
        view.toggle()  # the big Start pill
        wait(lambda: view.size != (0, 0))
        assert ("start", view.format) in calls
        assert view.size == (90, 160)  # the picture is on screen, inside the phone frame
        assert view.control is False and view.warning.winfo_manager()  # the yellow card shows
        assert "Stop" in view.start_button._text
        view.ai_toggle.toggle()
        assert flags["ai_control"] is True
        view._down(types.SimpleNamespace(x=45, y=40))
        view._up(types.SimpleNamespace(x=45, y=40))
        wait(lambda: any(kind == "input" for kind, _ in calls))
        assert ("input", {"type": "tap", "x": 0.5, "y": 0.25}) in calls
        assert "nåede ikke frem" in view.status.cget("text")
        view.toggle()  # Stop
        time.sleep(0.2)
        assert ("stop", None) in calls and not view.running
        assert not view.warning.winfo_manager() and "Start" in view.start_button._text
        before = len(calls)
        view._up(types.SimpleNamespace(x=45, y=40))
        root.update()
        assert len(calls) == before  # nothing goes to the phone once stopped
    finally:
        loop.call_soon_threadsafe(loop.stop)
        root.destroy()
