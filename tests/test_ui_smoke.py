from __future__ import annotations

import contextlib
import gc
import os

import pytest

# Force an isolated config directory so the UI never touches the user's data.
os.environ.setdefault("XDG_CONFIG_HOME", "/tmp/h4xtor-ui-test-smoke")


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    # Config() reads platformdirs (not XDG_CONFIG_HOME on Windows/macOS): never touch real data.
    monkeypatch.setattr("h4xtor_share.config.user_config_dir", lambda _n: str(tmp_path / "cfg"))
    monkeypatch.setattr("h4xtor_share.config.user_downloads_dir", lambda: str(tmp_path / "dl"))


@pytest.fixture(autouse=True)
def _free_tk_on_main_thread():
    # Closed apps leave Tk variables in reference cycles. Left to the garbage
    # collector they may be freed on the asyncio thread, which aborts Tcl
    # ("Tcl_AsyncDelete: async handler deleted by the wrong thread").
    yield
    gc.collect()


def _can_build_ui() -> bool:
    import tempfile
    from unittest import mock

    scratch = tempfile.mkdtemp(prefix="h4x-ui-probe-")
    with (
        mock.patch("h4xtor_share.config.user_config_dir", lambda _n: scratch),
        mock.patch("h4xtor_share.config.user_downloads_dir", lambda: scratch),
    ):
        return _probe_ui()


def _probe_ui() -> bool:
    try:
        from h4xtor_share.app import H4xtorShareApp

        app = H4xtorShareApp(enable_tray=False)
    except Exception:
        # No display server, missing Tk runtime or tkdnd library: skip.
        return False
    with contextlib.suppress(Exception):
        app.close()
    del app
    gc.collect()
    return True


def _new_app():
    """Build the app; skip when the CI runner's Tk install is broken (seen on Windows)."""
    import tkinter

    from h4xtor_share.app import H4xtorShareApp

    try:
        return H4xtorShareApp(enable_tray=False)
    except tkinter.TclError as error:
        pytest.skip(f"Tk runtime unavailable on this runner: {error}".splitlines()[0])


@pytest.mark.skipif(
    not _can_build_ui(),
    reason="Tk/tkdnd display server unavailable",
)
def test_ui_smoke_builds_and_shows_peer_state() -> None:
    from h4xtor_share.models import Peer, PeerStatus, TransferProgress

    app = _new_app()
    try:
        peer = Peer(
            device_id="ab" * 16,
            name="SmokePeer",
            address="192.168.1.50",
            port=47474,
            fingerprint="cd" * 32,
            platform="linux",
        )
        app.peers[peer.device_id] = peer
        app._upsert_peer(peer)
        app._update_peer_status(PeerStatus(peer.device_id, online=True, rtt_ms=8.0))
        app._update_transfer(
            TransferProgress(
                transfer_id="e" * 32,
                file_name="movie.mp4",
                sent=500,
                total=1000,
                direction="send",
            )
        )
        app.update_idletasks()
        app.update()
        assert peer.device_id in app.device_cards
        assert app.transfer_bars
        assert app.history.devices()
        for page in ("transfers", "clipboard", "history", "settings", "share"):
            app.show_page(page)
            app.update()
    finally:
        app.close()


@pytest.mark.skipif(
    not _can_build_ui(),
    reason="Tk/tkdnd display server unavailable",
)
def test_stale_duplicates_and_removal() -> None:
    from h4xtor_share.models import Peer, PeerStatus

    app = _new_app()
    try:
        current = Peer("11" * 16, "SM-S928B", "192.168.0.190", 47474, "aa" * 32, "android")
        stale = Peer("22" * 16, "S24 Ultra", "192.168.0.190", 47474, "bb" * 32, "android")
        app.config_store.trust_outbound_peer(current.device_id, "t" * 40, "aa" * 32, "SM")
        app._upsert_peer(stale)
        assert stale.device_id in app.device_cards
        app._upsert_peer(current)
        assert stale.device_id not in app.device_cards  # untrusted duplicate dropped
        app._update_peer_status(PeerStatus(current.device_id, True, 5.0))
        app._upsert_peer(stale)
        assert stale.device_id not in app.device_cards  # stale record ignored

        lonely = Peer("33" * 16, "Old laptop", "192.168.0.50", 47474, "cc" * 32, "windows")
        app._upsert_peer(lonely)
        for _ in range(3):
            app._update_peer_status(PeerStatus(lonely.device_id, False, None))
        assert lonely.device_id not in app.device_cards  # unpaired + silent = gone

        other = Peer("44" * 16, "Tablet", "192.168.0.60", 47474, "dd" * 32, "android")
        app._upsert_peer(other)
        app.remove_device(other)
        assert other.device_id not in app.device_cards
        app._upsert_peer(other)
        assert other.device_id not in app.device_cards  # stays hidden
        app.update()
    finally:
        app.close()


def test_scrollframe_wheel_works_over_child_widgets() -> None:
    import tkinter as tk
    from types import SimpleNamespace

    from h4xtor_share.ui_kit import ScrollFrame, Theme

    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}".splitlines()[0])
    try:
        root.geometry("300x200+120+120")
        # winfo_containing asks the OS which window is on top at that point.
        root.attributes("-topmost", True)
        root.lift()
        scroll = ScrollFrame(root, Theme(root, dark=False))
        scroll.pack(fill="both", expand=True)
        labels = [tk.Label(scroll.inner, text=f"row {i}") for i in range(80)]
        for label in labels:
            label.pack()
        root.update()
        child = labels[2]
        event = SimpleNamespace(
            widget=child,
            x_root=child.winfo_rootx() + 2,
            y_root=child.winfo_rooty() + 2,
            num=5,
            delta=0,
        )
        assert ScrollFrame._under_pointer(event) is scroll
        before = scroll.canvas.yview()[0]
        ScrollFrame._on_wheel(event)  # the old code ignored wheel over children
        assert scroll.canvas.yview()[0] > before
    finally:
        root.destroy()


@pytest.mark.skipif(
    not _can_build_ui(),
    reason="Tk/tkdnd display server unavailable",
)
def test_history_empty_state_and_forget_needs_confirmation() -> None:
    from h4xtor_share.history import HistoryStore
    from h4xtor_share.models import Peer

    app = _new_app()
    try:
        app.history = HistoryStore()  # in-memory, isolated from earlier tests
        app.show_page("history")
        assert app.history_empty.place_info()  # empty table explains itself
        peer = Peer("55" * 16, "Pixel", "192.168.0.70", 47474, "ee" * 32, "android")
        app.history.record_received_text(peer, "hello")
        app._refresh_history()
        assert not app.history_empty.place_info()

        forgotten: list[Peer] = []
        app.forget_peer = forgotten.append  # type: ignore[method-assign]
        app.confirm_forget(peer)
        app.update()
        assert not forgotten  # nothing happens until the user confirms
    finally:
        app.close()


@pytest.mark.skipif(
    not _can_build_ui(),
    reason="Tk/tkdnd display server unavailable",
)
def test_transfers_filter_remove_and_delete(tmp_path) -> None:
    from h4xtor_share.models import FileReceived, Peer, TransferProgress

    app = _new_app()
    try:
        peer = Peer("66" * 16, "Pixel", "192.168.0.80", 47474, "ff" * 32, "android")
        app.peers[peer.device_id] = peer
        received = tmp_path / "shot.png"
        received.write_bytes(b"x" * 10)
        app._handle_core_event(FileReceived(peer.device_id, "Pixel", received, 10, "r" * 32))
        app._update_transfer(TransferProgress("s" * 32, "big.iso", 5, 100, "send", "Pixel"))
        app.update()
        assert app.transfer_chips["receive"]._text == "Modtaget  1"
        assert "1 modtaget" in app.transfer_summary.cget("text")

        app.set_transfer_filter("receive")
        app.update()
        assert app.transfer_rows["r" * 32].card.winfo_ismapped()
        assert not app.transfer_rows["s" * 32].card.winfo_ismapped()

        app.remove_transfer("s" * 32)  # active rows stay until cancelled
        assert "s" * 32 in app.transfer_rows

        app.set_transfer_filter("active")
        app.update()
        assert app.transfer_rows["s" * 32].card.winfo_ismapped()
        app._update_transfer(TransferProgress("s" * 32, "big.iso", 100, 100, "send", "Pixel"))
        app.update()
        assert not app.transfer_rows["s" * 32].card.winfo_ismapped()  # done leaves "I gang"
        app.set_transfer_filter("receive")

        state = app.transfers["r" * 32]
        assert app.can_delete_transfer(state)
        app.confirm_delete_transfer(state)
        app.update()
        assert received.exists()  # nothing happens until the user confirms
        app.delete_transfer_file(state)
        assert not received.exists()
        assert "r" * 32 not in app.transfer_rows
        app.update()
        assert app.transfer_empty.winfo_ismapped()  # "Intet modtaget endnu."
    finally:
        app.close()


@pytest.mark.skipif(
    not _can_build_ui(),
    reason="Tk/tkdnd display server unavailable",
)
def test_iphone_access_turns_itself_off_when_port_is_taken() -> None:
    import socket
    import time

    app = _new_app()
    blocker = socket.socket()
    try:
        blocker.bind(("0.0.0.0", 0))
        blocker.listen()
        app.web_share.port = blocker.getsockname()[1]
        app.show_page("iphone")
        app.set_web_enabled(True)
        deadline = time.time() + 10
        while app.web_share.enabled and time.time() < deadline:
            app.update()
            time.sleep(0.05)
        assert not app.web_share.enabled  # no QR code for a dead link
        assert not app.web_toggle.value
    finally:
        blocker.close()
        app.close()


def _paired_app(count: int, tmp_path, monkeypatch, extra_caps: tuple[str, ...] = ()):
    from h4xtor_share.models import Peer

    app = _new_app()
    peers = []
    for index in range(count):
        peer = Peer(
            f"{index + 1:02x}" * 16,
            ["Mobil", "Bærbar", "Tablet"][index],
            f"192.168.1.{50 + index}",
            47474,
            f"{index + 1:02x}" * 32,
            "android",
            capabilities=(("folders",) if index != 1 else ()) + extra_caps,
        )
        app.config_store.trust_outbound_peer(peer.device_id, "t" * 40, peer.fingerprint, peer.name)
        app.peers[peer.device_id] = peer
        app._upsert_peer(peer)
        peers.append(peer)
    return app, peers


def _texts(widget) -> list[str]:
    found = []
    for child in widget.winfo_children():
        with contextlib.suppress(Exception):
            found.append(str(child.cget("text")))
        found.extend(_texts(child))
    return found


def _pump(app, until, seconds: float = 10.0) -> None:
    import time

    deadline = time.time() + seconds
    while not until() and time.time() < deadline:
        app.update()
        time.sleep(0.02)
    assert until()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_chooser_offers_all_devices_only_with_two_or_more(tmp_path, monkeypatch) -> None:
    import tkinter as tk

    app, _peers = _paired_app(3, tmp_path, monkeypatch)
    try:
        app._choose_peer(lambda _p: None, "Vælg", all_callback=lambda: None)
        app.update()
        modals = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        assert "Alle enheder" in _texts(modals[-1])
        modals[-1].destroy()
        # no all_callback (e.g. other callers) -> no extra card
        app._choose_peer(lambda _p: None, "Vælg")
        app.update()
        modals = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        assert "Alle enheder" not in _texts(modals[-1])
    finally:
        app.close()

    app, _peers = _paired_app(2, tmp_path, monkeypatch)
    try:
        app._choose_peer(lambda _p: None, "Vælg", all_callback=lambda: None)
        app.update()
        modals = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        assert "Alle enheder" in _texts(modals[-1])
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_send_text_to_all_reports_one_summary(tmp_path, monkeypatch) -> None:
    app, peers = _paired_app(3, tmp_path, monkeypatch)
    sent: list[str] = []
    summaries = []

    async def send_clipboard(peer, text):
        if peer.name == "Bærbar":
            raise RuntimeError("Bærbar er offline")
        sent.append(peer.name)

    async def send_link(peer, url):
        sent.append(peer.name)

    app.client.send_clipboard = send_clipboard
    app.client.send_link = send_link
    original = app._show_send_all_summary
    app._show_send_all_summary = lambda group: (summaries.append(group), original(group))
    try:
        assert app._send_to_all("text", "hej alle")
        _pump(app, lambda: summaries)
        group = summaries[0]
        assert sorted(sent) == ["Mobil", "Tablet"]
        assert group.total == 3 and len(group.ok) == 2
        assert group.problems == [("Bærbar", "Bærbar er offline")]
        assert len(summaries) == 1

        summaries.clear()
        assert app._send_to_all("text", "https://example.com")
        _pump(app, lambda: summaries)
        assert len(summaries[0].ok) == 3
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_send_files_and_folders_to_all_skips_unsupported_and_reports(
    tmp_path, monkeypatch
) -> None:
    app, peers = _paired_app(3, tmp_path, monkeypatch)
    (tmp_path / "dir").mkdir()
    (tmp_path / "dir" / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    got: list[tuple[str, str]] = []
    summaries = []

    async def send_file(peer, path, progress):
        if peer.name == "Tablet":
            raise RuntimeError("Tablet svarer ikke")
        got.append((peer.name, path.name))

    async def send_folder(peer, path, progress):
        got.append((peer.name, path.name))

    app.client.send_file = send_file
    app.client.send_folder = send_folder
    app._show_send_all_summary = summaries.append
    try:
        assert app._send_to_all("paths", [tmp_path / "dir", tmp_path / "b.txt"])
        _pump(app, lambda: summaries)
        group = summaries[0]
        # Mobil gets both, Bærbar (no folder support) only the file, Tablet's file fails.
        assert sorted(got) == [
            ("Bærbar", "b.txt"),
            ("Mobil", "b.txt"),
            ("Mobil", "dir"),
            ("Tablet", "dir"),
        ]
        assert sorted(group.ok) == ["Bærbar", "Mobil"]
        assert group.problems == [("Tablet", "Tablet svarer ikke")]

        summaries.clear()
        got.clear()
        assert app._send_to_all("paths", [tmp_path / "dir"])
        _pump(app, lambda: summaries)
        # Bærbar cannot take folders: reported, not sent.
        assert ("Bærbar", "Kan ikke modtage mapper endnu.") in summaries[0].problems
        assert sorted(got) == [("Mobil", "dir"), ("Tablet", "dir")]
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_api_send_all_returns_result_per_device(tmp_path, monkeypatch) -> None:
    import asyncio

    app, peers = _paired_app(2, tmp_path, monkeypatch)

    async def send_link(peer, url):
        if peer.name == "Bærbar":
            raise RuntimeError("nede")

    app.client.send_link = send_link
    try:
        future = asyncio.run_coroutine_threadsafe(
            app._api_send_all("link", "https://example.com"), app.runtime.loop
        )
        _pump(app, future.done)
        results = {item["name"]: item for item in future.result()}
        assert results["Mobil"]["ok"] is True and results["Mobil"]["error"] == ""
        assert results["Bærbar"]["ok"] is False and results["Bærbar"]["error"] == "nede"
    finally:
        app.close()


PHONE_CAPS = ("notifications", "sms", "screenshot-request", "find-phone", "remote-control")


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _buttons(widget) -> dict:
    return {w._text: w for w in _walk(widget) if hasattr(w, "_text") and hasattr(w, "command")}


def _recorder(app, name: str, result=None, error: Exception | None = None) -> list:
    calls: list = []

    async def method(*args):
        calls.append(args)
        if error is not None:
            raise error
        return result

    setattr(app.client, name, method)
    return calls


def _notification(peer, **kwargs):
    from h4xtor_share.models import NotificationReceived

    values = {
        "peer_id": peer.device_id,
        "peer_name": peer.name,
        "key": "0|com.whatsapp|1",
        "package": "com.whatsapp",
        "app": "WhatsApp",
        "title": "Mor",
        "text": "Kommer du til middag?",
        "time": 0,
        "icon_png": b"",
        "can_reply": True,
        "can_dismiss": True,
    }
    values.update(kwargs)
    return NotificationReceived(**values)


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_phone_pages_build_empty_and_with_a_phone(tmp_path, monkeypatch) -> None:
    app, peers = _paired_app(1, tmp_path, monkeypatch, PHONE_CAPS)
    try:
        _recorder(app, "sms_threads", [])
        for page in ("notifications", "sms", "remote", "settings"):
            app.show_page(page)
            app.update()
        assert "Find telefon" in _buttons(app.remote_scroll.inner)
    finally:
        app.close()
    # A phone that does not know the new features: controls disabled with a hint.
    app, peers = _paired_app(1, tmp_path, monkeypatch)
    try:
        app.show_page("remote")
        app.update()
        assert "Telefonen skal opdateres" in " ".join(_texts(app.pages["remote"]))
        app.show_page("sms")
        app.update()
        assert "Ingen forbundne enheder kan sende og modtage SMS" in app.sms_notice.cget("text")
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_notifications_card_reply_dismiss_remove(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from h4xtor_share.models import NotificationRemoved

    app, peers = _paired_app(1, tmp_path, monkeypatch, PHONE_CAPS)
    peer = peers[0]
    shown: list[str] = []
    app._notify = lambda message, tone="neutral": shown.append(message)
    root = Path(__file__).resolve().parents[1] / "src" / "h4xtor_share"
    icon = root / "chrome_extension" / "icons" / "icon48.png"
    try:
        app._handle_core_event(_notification(peer, icon_png=icon.read_bytes()))
        app._handle_core_event(_notification(peer, key="b", app="SMS", icon_png=b"junk"))
        app.update()
        assert [e.key for e in app.notif_entries] == ["b", "0|com.whatsapp|1"]  # newest first
        assert app.notif_entries[1].photo is not None  # real icon decoded
        assert app.notif_entries[0].photo is None  # broken icon -> initial fallback
        assert shown[0] == "WhatsApp: Mor – Kommer du til middag?"
        assert app.nav_badges["notifications"].cget("text") == "2"
        # An update of the same key neither duplicates nor notifies again.
        app._handle_core_event(_notification(peer, text="Svar mig"))
        assert len(app.notif_entries) == 2 and len(shown) == 2
        assert app.notif_entries[1].text == "Svar mig"

        app.show_page("notifications")
        assert app.nav_badges["notifications"].cget("text") == ""

        calls = _recorder(app, "notification_action")
        entry = app.notif_entries[1]
        app._notif_toggle_reply(entry)
        assert entry.reply_row is not None
        app._notif_reply(entry, "Ja, jeg kommer")
        _pump(app, lambda: calls)
        assert calls == [(peer, "0|com.whatsapp|1", "reply", "Ja, jeg kommer")]
        app.update()
        app._notif_dismiss(entry)
        _pump(app, lambda: len(app.notif_entries) == 1)
        assert calls[-1] == (peer, "0|com.whatsapp|1", "dismiss")

        app._handle_core_event(NotificationRemoved(peer.device_id, peer.name, "b"))
        assert app.notif_entries == []
        assert "Ingen notifikationer endnu" in app.notif_empty.cget("text")

        app.config_store.set_flag("show_phone_notifications", False)
        shown.clear()
        app._handle_core_event(_notification(peer, key="c"))
        assert shown == []
        app._notif_clear_all()
        assert app.notif_entries == []
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_sms_page_threads_messages_live_update_and_errors(tmp_path, monkeypatch) -> None:
    from h4xtor_share.models import SmsReceived

    app, peers = _paired_app(1, tmp_path, monkeypatch, PHONE_CAPS)
    peer = peers[0]
    shown: list[str] = []
    app._notify = lambda message, tone="neutral": shown.append(message)
    threads = [
        {
            "thread_id": "12",
            "address": "+4512345678",
            "name": "Mor",
            "snippet": "Hej",
            "time": 1760090000000,
            "unread": False,
        },
        {
            "thread_id": "13",
            "address": "+4587654321",
            "name": "",
            "snippet": "Tak",
            "time": 1760080000000,
            "unread": True,
        },
    ]
    messages = [
        {"id": "1", "address": "+4512345678", "body": "Hej", "time": 1760090000000,
         "outgoing": False},
        {"id": "2", "address": "+4512345678", "body": "Hej mor", "time": 1760090100000,
         "outgoing": True},
    ]
    _recorder(app, "sms_threads", threads)
    _recorder(app, "sms_messages", messages)
    sent = _recorder(app, "send_sms")
    try:
        app.show_page("sms")
        _pump(app, lambda: app.sms_threads.get(peer.device_id))
        app.update()
        assert len(app.sms_threads[peer.device_id]) == 2
        app._sms_select(app.sms_threads[peer.device_id][0])
        _pump(app, lambda: (peer.device_id, "12") in app.sms_messages)
        app.update()
        assert "Mor  ·  +4512345678" in app.sms_title.cget("text")
        assert len(app.sms_msg_scroll.inner.winfo_children()) == 2  # two bubbles

        # A live SMS in the open thread appears; one in another thread marks it unread.
        app._handle_core_event(
            SmsReceived(
                peer.device_id,
                peer.name,
                "12",
                "+4512345678",
                "Mor",
                "Middag kl. 18?",
                1760091000000,
            )
        )
        app.update()
        assert len(app.sms_msg_scroll.inner.winfo_children()) == 3
        assert app.sms_threads[peer.device_id][0]["snippet"] == "Middag kl. 18?"
        assert shown[-1] == "SMS fra Mor: Middag kl. 18?"
        app._handle_core_event(
            SmsReceived(peer.device_id, peer.name, "13", "+4587654321", "", "Ring", 1760092000000)
        )
        top = app.sms_threads[peer.device_id][0]
        assert top["thread_id"] == "13" and top["unread"] is True
        assert shown[-1] == "SMS fra +4587654321: Ring"

        app.sms_box.insert("1.0", "Kl. 18 passer")
        app._sms_send()
        _pump(app, lambda: sent)
        assert sent == [(peer, "+4512345678", "Kl. 18 passer")]
        _pump(app, lambda: not app.sms_box.get("1.0", "end").strip())
        assert len(app.sms_msg_scroll.inner.winfo_children()) == 4

        app._sms_start_new("+4500000000")
        assert app.sms_current == {"thread_id": "", "address": "+4500000000", "name": ""}
    finally:
        app.close()

    app, peers = _paired_app(1, tmp_path, monkeypatch, PHONE_CAPS)
    _recorder(app, "sms_threads", error=RuntimeError("SMS er slået fra på telefonen."))
    try:
        app.show_page("sms")
        _pump(app, lambda: "slået fra" in app.sms_notice.cget("text"))
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_remote_buttons_call_the_client_and_screenshot_opens(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from h4xtor_share.models import FileReceived

    app, peers = _paired_app(1, tmp_path, monkeypatch, PHONE_CAPS)
    peer = peers[0]
    find = _recorder(app, "find_phone", True)
    shot = _recorder(app, "request_screenshot")
    volume = _recorder(app, "set_volume", 30)
    speak = _recorder(app, "speak")
    paper = _recorder(app, "set_wallpaper")
    opened: list[str] = []
    app.open_path_safely = opened.append
    image = tmp_path / "bg.png"
    image.write_bytes(b"png")
    monkeypatch.setattr(
        "h4xtor_share.phone_pages.filedialog.askopenfilename", lambda **_k: str(image)
    )
    try:
        app.open_remote(peer)
        app.update()
        assert app.active_page == "remote" and app.remote_peer_id == peer.device_id
        app.remote_find()
        app.remote_stop_ring()
        _pump(app, lambda: len(find) == 2)
        assert find == [(peer, True), (peer, False)]
        app.remote_scale.set(30)
        app.remote_set_volume()
        app.remote_speak_var.set("Hvor er du?")
        app.remote_speak()
        app.remote_wallpaper()
        _pump(app, lambda: volume and speak and paper)
        assert volume == [(peer, 30)] and speak == [(peer, "Hvor er du?")]
        assert paper == [(peer, Path(image))]

        app.remote_screenshot()
        _pump(app, lambda: app.pending_screenshot is not None)
        other = FileReceived("z" * 32, "Anden", Path("Skaermbillede-1.png"), 1)
        app._maybe_open_screenshot(other)  # wrong phone
        assert opened == []
        app._maybe_open_screenshot(FileReceived(peer.device_id, peer.name, Path("foto.png"), 1))
        assert opened == []  # not a screenshot
        app._maybe_open_screenshot(
            FileReceived(peer.device_id, peer.name, Path("Skaermbillede-20261010-1.png"), 1)
        )
        assert opened == ["Skaermbillede-20261010-1.png"]
        assert app.pending_screenshot is None
        assert shot == [(peer,)]
    finally:
        app.close()


class FakeDrive:
    def __init__(self, configured: bool, connected: bool = False) -> None:
        self.configured, self.connected = configured, connected
        self.files: list[str] = []
        self.disconnected = False

    def status(self):
        return {
            "configured": self.configured,
            "connected": self.connected,
            "email": "lennart@example.com" if self.connected else "",
        }

    async def connect(self, open_url):
        self.connected = True
        return "lennart@example.com"

    async def list_root(self, limit: int = 20):
        return self.files

    async def disconnect(self):
        self.connected = False
        self.disconnected = True


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_google_drive_section_states(tmp_path, monkeypatch) -> None:
    import tkinter as tk

    app, _peers = _paired_app(1, tmp_path, monkeypatch)

    def modal_count() -> int:
        return len([w for w in app.winfo_children() if isinstance(w, tk.Toplevel)])

    try:
        app.gdrive = FakeDrive(configured=False)
        app._drive_render()
        assert "Forbind Google Drive" in _buttons(app.drive_body)
        app._drive_connect()  # not configured -> setup help, nothing contacts Google
        app.update()
        modals = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        assert any("Google Cloud Console" in " ".join(_texts(m)) for m in modals)
        assert app.gdrive.connected is False

        app.gdrive = FakeDrive(configured=True)
        app._drive_render()
        app._drive_connect()
        assert "Venter på Google" in " ".join(_texts(app.drive_body))
        _pump(app, lambda: app.gdrive.connected and not app.drive_busy)
        texts = " ".join(_texts(app.drive_body))
        assert "Forbundet som lennart@example.com" in texts
        assert {"Test forbindelse", "Afbryd"} <= set(_buttons(app.drive_body))

        before = modal_count()
        app._drive_test()  # empty Drive is fine and explained
        _pump(app, lambda: modal_count() > before)
        app.gdrive.files = ["a.txt", "b.txt"]
        app._drive_test()
        app._drive_disconnect()
        _pump(app, lambda: "Forbind Google Drive" in _buttons(app.drive_body))
        assert app.gdrive.disconnected
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_target_menu_all_devices(tmp_path, monkeypatch) -> None:
    app, peers = _paired_app(2, tmp_path, monkeypatch)
    try:
        app.select_all_devices()
        app.update()
        assert app._all_selected() and app._drop_target_peer() is None
        assert app.target_button._text == "Til: Alle enheder ▾"
        retried: list = []
        assert app._resolve_peer(None, lambda *a, **k: retried.append(k)) is None
        assert retried == [{"to_all": True}]  # no chooser: straight to everyone
        app.select_peer(peers[0].device_id)
        assert not app._all_selected()
        assert app.target_button._text == "Til: Mobil ▾"
    finally:
        app.close()
