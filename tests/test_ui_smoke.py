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


@pytest.mark.skipif(
    not _can_build_ui(),
    reason="Tk/tkdnd display server unavailable",
)
def test_update_dialog_flow(tmp_path, monkeypatch) -> None:
    import time

    from h4xtor_share import update_pages
    from h4xtor_share.updater import ChangelogEntry, Release

    app = _new_app()
    try:
        app.config_store.data.pop("update_skip", None)
        app.config_store.data.pop("update_later", None)
        new_exe = tmp_path / "new.exe"
        new_exe.write_bytes(b"exe")
        release = Release("9.0.0", "2030-01-01", "https://example.invalid", {})
        entries = [
            ChangelogEntry(f"9.0.{n}", "2030-01-01", {"Nyt": [f"punkt {n}"]}) for n in range(5)
        ]

        # "Senere": closes and is not asked again straight away.
        app._show_update_dialog(release, entries)
        app.update()
        buttons = {b._text: b for b in app._update_buttons.winfo_children()}
        assert set(buttons) == {"Opdatér nu", "Senere", "Spring denne version over"}
        buttons["Senere"].command()
        assert app._update_modal is None
        assert not app.updater.should_prompt("9.0.0")

        # "Opdatér nu": downloads, verifies the checksum, hands over to the helper.
        started: list = []
        monkeypatch.setattr(update_pages, "can_self_install", lambda: True)
        monkeypatch.setattr(update_pages, "start_helper", lambda path, folder: started.append(path))
        monkeypatch.setattr(app, "close", lambda: started.append("closed"))

        async def download(_release, _folder, progress):
            progress(1, 2)
            return new_exe

        monkeypatch.setattr(app.updater, "download", download)
        app._show_update_dialog(release, entries)
        app.update()
        {b._text: b for b in app._update_buttons.winfo_children()}["Opdatér nu"].command()
        deadline = time.time() + 10
        while "closed" not in started and time.time() < deadline:
            app.update()
            time.sleep(0.05)
        assert started == [new_exe, "closed"]

        app.show_changelog()  # the offline log opens from the shipped/cached changelog
        app.update()
        app._show_welcome("0.0.1")
        app.update()
    finally:
        monkeypatch.undo()  # the real close() again
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_wifi_5g_page_switches_proxy_and_finds_sharing_phone(tmp_path, monkeypatch) -> None:
    import socket

    from h4xtor_share import sysproxy

    calls: list[str] = []
    monkeypatch.setattr(sysproxy, "apply", lambda url: calls.append(f"apply {url}") or {"x": 1})
    monkeypatch.setattr(sysproxy, "restore", lambda saved, url: calls.append(f"restore {saved}"))
    app, peers = _paired_app(1, tmp_path, monkeypatch, ("net-gateway",))
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            app.netmerge.port = sock.getsockname()[1]
        app.netmerge.adapters = lambda: [("Wi-Fi", "127.0.0.1")]

        async def healthy(link) -> None:
            link.healthy, link.latency = True, 0.02

        async def status(peer):
            return {"enabled": True, "network": "5G"}

        monkeypatch.setattr(app.netmerge, "probe", healthy)
        monkeypatch.setattr(app.client, "net_share_status", status)
        app.show_page("netmerge")
        assert app.netmerge_status.cget("text") == "Slået fra"

        app.set_netmerge_enabled(True)
        _pump(app, lambda: app.config_store.data.get("netmerge_proxy_saved") == {"x": 1})
        assert app.netmerge.running and calls == [f"apply {app.netmerge.pac_url}"]
        _pump(app, lambda: f"phone:{peers[0].device_id}" in app.netmerge.links)
        app._refresh_netmerge()
        texts = " ".join(_texts(app.netmerge_list))
        assert "Mobil" in texts and "Telefon · 5G" in texts and "Wi-Fi" in texts
        assert app.netmerge_status.cget("text").startswith("Kører · 2 links")

        app.set_netmerge_enabled(False)
        _pump(app, lambda: "netmerge_proxy_saved" not in app.config_store.data)
        assert not app.netmerge.running and calls[-1] == "restore {'x': 1}"
        assert not app.netmerge_toggle.value

        # On at quit: the system proxy is put back, but it switches on again next start.
        app.set_netmerge_enabled(True)
        _pump(app, lambda: app.config_store.data.get("netmerge_proxy_saved") == {"x": 1})
    finally:
        app.close()
    assert calls[-1] == "restore {'x': 1}"
    assert app.config_store.data["netmerge_enabled"] is True


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_bluetooth_fallback_switches_route_and_back(tmp_path, monkeypatch) -> None:
    import socket

    from h4xtor_share import bluetooth
    from h4xtor_share.models import Peer

    app, peers = _paired_app(1, tmp_path, monkeypatch, ("bluetooth",))
    phone = peers[0]
    opened: list[tuple[str, str]] = []
    phone_ends: list[bluetooth.Bridge] = []

    def fake_open_bridge(address, device_id, local_port, expected_id=None, on_closed=None):
        # The "phone" end runs the real bridge too, over a socket pair instead of RFCOMM.
        opened.append((address, expected_id))
        left, right = socket.socketpair()
        phone_ends.append(bluetooth.Bridge(right, phone.device_id, 1, odd=False).start())
        pc = bluetooth.Bridge(left, device_id, local_port, odd=True, on_closed=on_closed).start()
        assert pc.wait_hello(5) == expected_id
        return pc

    monkeypatch.setattr(bluetooth, "supported", lambda: True)
    monkeypatch.setattr(bluetooth, "paired_devices", lambda: [("AA:BB:CC:DD:EE:FF", "Mobil")])
    monkeypatch.setattr(bluetooth, "open_bridge", fake_open_bridge)
    try:
        # Wi-Fi can't reach the phone: the health check asks for Bluetooth by itself.
        app.event_queue.put(("bt_maybe", phone))
        _pump(app, lambda: app.peers[phone.device_id].transport == "bluetooth")
        routed = app.peers[phone.device_id]
        bridge = app._bt_bridges[phone.device_id]
        assert (routed.address, routed.port) == ("127.0.0.1", bridge.port)
        assert opened == [("AA:BB:CC:DD:EE:FF", phone.device_id)]
        assert app.config_store.data["bt_addresses"][phone.device_id] == "AA:BB:CC:DD:EE:FF"
        # The temporary bridge address is never saved as the phone's address.
        assert app.config_store.data["known_peers"][phone.device_id]["address"] == "192.168.1.50"

        # At most one automatic attempt a minute.
        app._maybe_bluetooth(app._bt_before[phone.device_id])
        assert len(opened) == 1

        # The phone shows up on Wi-Fi again: stay on Bluetooth until that address answers…
        newer = Peer(phone.device_id, phone.name, "192.168.1.77", 47474, phone.fingerprint,
                     "android", capabilities=phone.capabilities)
        app._upsert_peer(newer)
        assert app.peers[phone.device_id].transport == "bluetooth"
        assert app._bt_before[phone.device_id].address == "192.168.1.77"
        # …then switch back to it and close the bridge.
        app.event_queue.put(("bt_wifi_back", phone.device_id))
        _pump(app, lambda: app.peers[phone.device_id].transport != "bluetooth")
        assert app.peers[phone.device_id].address == "192.168.1.77"
        assert phone.device_id not in app._bt_bridges and bridge.closed
        _pump(app, lambda: phone_ends[0].closed)  # the phone notices the link is gone
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_bluetooth_finds_and_pairs_a_phone_never_seen_on_wifi(tmp_path, monkeypatch) -> None:
    """Paired only in Windows' Bluetooth settings: search, pair with code, send, reconnect."""
    import asyncio
    import socket
    import threading

    from h4xtor_share import bluetooth
    from h4xtor_share.config import Config
    from h4xtor_share.crypto import ensure_certificate, server_ssl_context
    from h4xtor_share.models import ClipboardReceived, PairingPrompt
    from h4xtor_share.server import ShareServer

    # The "phone": the real protocol-v1 server, reachable only through the bridge.
    phone_config = Config(tmp_path / "phone" / "config.json")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        phone_config.data.update(port=int(probe.getsockname()[1]), device_name="S24 Ultra",
                                 platform="android")
    cert, key, phone_fp = ensure_certificate(phone_config.path.parent, "S24 Ultra")
    phone_events: list[object] = []
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    phone_server = ShareServer(phone_config, server_ssl_context(cert, key), phone_fp,
                               phone_events.append, host="127.0.0.1")
    asyncio.run_coroutine_threadsafe(phone_server.start(), loop).result(20)
    phone_id = phone_config.device_id

    monkeypatch.setattr(bluetooth, "supported", lambda: True)  # macOS too: the radio is faked
    app = _new_app()
    opened: list[tuple[str, str | None]] = []
    phone_ends: list[bluetooth.Bridge] = []

    def fake_open_bridge(address, device_id, local_port, expected_id=None, on_closed=None):
        opened.append((address, expected_id))
        if address != "22:22:22:22:22:22":  # the headphones: no h4xtor share there
            raise OSError(10108, "service not found")
        left, right = socket.socketpair()
        phone_ends.append(
            bluetooth.Bridge(right, phone_id, phone_config.port, odd=False).start()
        )
        pc = bluetooth.Bridge(left, device_id, local_port, odd=True, on_closed=on_closed).start()
        assert pc.wait_hello(5) == phone_id
        return pc

    paired = [
        ("11:11:11:11:11:11", "WH-1000XM5", False),
        ("22:22:22:22:22:22", "Galaxy S24", True),  # Bluetooth name differs from the app name
    ]
    monkeypatch.setattr(bluetooth, "supported", lambda: True)
    monkeypatch.setattr(bluetooth, "paired_devices", lambda: paired)
    monkeypatch.setattr(bluetooth, "open_bridge", fake_open_bridge)

    def auto_code(peer, response) -> None:  # stands in for typing the code shown on the phone
        prompt = next(e for e in phone_events if isinstance(e, PairingPrompt))

        async def confirm():
            await app.client.confirm_pairing(peer, str(response["pairing_id"]), prompt.code)
            return peer

        app.runtime.submit(confirm(), "pair_confirmed")

    monkeypatch.setattr(app, "_prompt_for_pairing_code", auto_code)
    try:
        from h4xtor_share.ui_kit import Button

        def buttons(widget) -> list[Button]:
            found = [widget] if isinstance(widget, Button) else []
            for child in widget.winfo_children():
                found += buttons(child)
            return found

        search = [b for b in buttons(app) if b._text == "Søg via Bluetooth"]
        assert search, "no 'Søg via Bluetooth' button"
        search[0].command()  # what a click on it runs
        _pump(app, lambda: phone_id in app.peers, 15)
        found = app.peers[phone_id]
        assert (found.name, found.transport, found.address) == ("S24 Ultra", "bluetooth",
                                                                "127.0.0.1")
        assert not app.config_store.is_trusted(phone_id)
        assert opened == [("22:22:22:22:22:22", None)]  # only the phone, not the headphones
        card_texts = " ".join(_texts(app.device_cards[phone_id].card))
        assert "fundet på Bluetooth" in card_texts and "127.0.0.1" not in card_texts

        # Click the device: pair with the code, over Bluetooth.
        app.pair_with_code(found)
        # Trust is stored first; the UI remembers the peer a moment later.
        _pump(app, lambda: app.config_store.is_trusted(phone_id)
              and phone_id in app.config_store.data.get("known_peers", {}), 15)
        assert phone_config.is_trusted(app.config_store.device_id)  # both ways
        known = app.config_store.data["known_peers"][phone_id]
        assert (known["address"], known["transport"]) == ("", "bluetooth")

        # Sharing works over the link.
        asyncio.run_coroutine_threadsafe(
            app.client.send_clipboard(app.peers[phone_id], "hej via bluetooth"), app.runtime.loop
        ).result(20)
        assert any(isinstance(e, ClipboardReceived) and e.text == "hej via bluetooth"
                   for e in phone_events)

        # Out of range: the phone stays in the list (offline) instead of vanishing…
        phone_ends[0].close()
        _pump(app, lambda: phone_id not in app._bt_bridges)
        kept = app.peers[phone_id]
        assert (kept.address, kept.transport) == ("", "bluetooth")
        assert not app.peer_status[phone_id].online
        # …and comes back on Bluetooth by itself (the remembered MAC first).
        app.event_queue.put(("bt_maybe", kept))
        _pump(app, lambda: phone_id in app._bt_bridges, 15)
        assert opened[-1] == ("22:22:22:22:22:22", phone_id)
        assert app.peers[phone_id].address == "127.0.0.1"
    finally:
        app.close()
        asyncio.run_coroutine_threadsafe(phone_server.stop(), loop).result(20)
        loop.call_soon_threadsafe(loop.stop)


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_bluetooth_search_explains_why_nothing_was_found(tmp_path, monkeypatch) -> None:
    from h4xtor_share import bluetooth

    monkeypatch.setattr(bluetooth, "supported", lambda: True)
    app = _new_app()
    shown: list[str] = []
    monkeypatch.setattr(app.toast, "show", lambda text, *a, **k: shown.append(text))
    try:
        monkeypatch.setattr(bluetooth, "paired_devices", lambda: [])
        app.scan_bluetooth(manual=True)
        _pump(app, lambda: not app._bt_scanning and any("Ingen parrede" in t for t in shown))

        def refuse(*_a, **_k):
            raise OSError(10108, "service not found")

        phone = [("AA:AA:AA:AA:AA:AA", "S24", True)]
        monkeypatch.setattr(bluetooth, "paired_devices", lambda: phone)
        monkeypatch.setattr(bluetooth, "open_bridge", refuse)
        app.scan_bluetooth(manual=True)
        _pump(app, lambda: any("Tillad forbindelse via Bluetooth" in t for t in shown))
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_pc_makes_wifi_direct_and_the_phone_joins(tmp_path, monkeypatch) -> None:
    from h4xtor_share import wifidirect_host
    from h4xtor_share.models import Peer, PeerStatus, WifiDirectJoined

    started: list[str] = []
    stopped: list[str] = []
    monkeypatch.setattr(wifidirect_host, "supported", lambda: None)
    monkeypatch.setattr(
        wifidirect_host.DirectHost,
        "start",
        lambda self, timeout=25.0: (
            started.append(self.ssid),
            setattr(self, "started_at", 1.0),
            setattr(self, "addresses", ["192.168.137.1"]),
        )
        and self.addresses,
    )
    monkeypatch.setattr(
        wifidirect_host.DirectHost, "running", property(lambda self: self.started_at > 0)
    )
    monkeypatch.setattr(
        wifidirect_host.DirectHost,
        "stop",
        lambda self: (stopped.append(self.ssid), setattr(self, "started_at", 0.0)),
    )
    app, peers = _paired_app(1, tmp_path, monkeypatch, ("wifi-direct-pc",))
    phone = peers[0]
    app.peer_status[phone.device_id] = PeerStatus(phone.device_id, True, 5.0)
    offers = _recorder(app, "offer_pc_wifi_direct")
    joined_phone = Peer(
        phone.device_id, phone.name, "192.168.137.42", 47474, phone.fingerprint, "android",
        capabilities=phone.capabilities,
    )
    info: list = []

    async def get_info(address, port, timeout_seconds=5.0):
        info.append((address, port))
        return joined_phone

    app.client.get_info = get_info
    try:
        app.show_page("settings")
        app.direct_name_var.set("DIRECT-h4-Test")
        app.direct_pass_var.set("hemmelig")
        app.toggle_direct_host()
        _pump(app, lambda: bool(offers))
        assert started == ["DIRECT-h4-Test"]
        assert "Kører" in app.direct_status.cget("text")
        assert "192.168.137.1" in app.direct_status.cget("text")
        assert offers[0][0].device_id == phone.device_id
        assert offers[0][1:] == ("DIRECT-h4-Test", "hemmelig", ["192.168.137.1"])
        stored = app.config_store.data["direct_host"]
        assert stored == {"ssid": "DIRECT-h4-Test", "pass": "hemmelig"}

        app._handle_event(
            "core_event",
            WifiDirectJoined(phone.device_id, phone.name, "192.168.137.42", 47474, "DIRECT-h4-T"),
        )
        _pump(app, lambda: app.peers[phone.device_id].transport == "wifi-direct")
        assert info[0] == ("192.168.137.42", 47474)
        assert app.peers[phone.device_id].address == "192.168.137.42"
        assert "forbundet: Mobil" in app.direct_status.cget("text")

        app.toggle_direct_host()
        assert stopped == ["DIRECT-h4-Test"]
        assert "Slukket" in app.direct_status.cget("text")
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_pc_wifi_direct_rejects_bad_names_before_starting(tmp_path, monkeypatch) -> None:
    from h4xtor_share import wifidirect_host

    monkeypatch.setattr(wifidirect_host, "supported", lambda: None)
    app = _new_app()
    errors: list[str] = []
    app._show_error = lambda error: errors.append(str(error))
    try:
        app.direct_name_var.set("Mit netværk")
        app.start_direct_host()
        assert errors and "DIRECT-h4-" in errors[0]
        assert app.direct_host is None
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_stop_all_cancels_every_running_send(tmp_path, monkeypatch) -> None:
    from concurrent.futures import Future

    app = _new_app()
    try:
        running, finished = Future(), Future()
        finished.set_result(None)
        app.batches.update(a=running, b=finished)
        cancelled: list[str] = []
        app.cancel_batch = cancelled.append
        app.stop_all_transfers()
        assert cancelled == ["a"]
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_pc_wifi_direct_can_be_retried_after_a_failed_start(tmp_path, monkeypatch) -> None:
    from h4xtor_share import wifidirect, wifidirect_host

    def fail(self, timeout=25.0):
        raise wifidirect.WifiDirectError("NetworkManager kunne ikke lave netværket: nej")

    monkeypatch.setattr(wifidirect_host, "supported", lambda: None)
    monkeypatch.setattr(wifidirect_host.DirectHost, "start", fail)
    app = _new_app()
    errors: list[str] = []
    app._show_error = lambda error: errors.append(str(error))
    try:
        app.direct_name_var.set("DIRECT-h4-Test")
        app.direct_pass_var.set("hemmelig")
        app.start_direct_host()
        _pump(app, lambda: bool(errors) and app.direct_host is None)
        assert "NetworkManager" in errors[0]
        assert "Slukket" in app.direct_status.cget("text")
        assert str(app.direct_name_entry.cget("state")) == "normal"
        assert app.direct_toggle.enabled
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_send_page_hero_and_tiles_follow_the_selection(tmp_path, monkeypatch) -> None:
    from h4xtor_share.app import TransferState
    from h4xtor_share.models import PeerStatus

    app, peers = _paired_app(2, tmp_path, monkeypatch)
    try:
        for peer in peers:
            app.peer_status[peer.device_id] = PeerStatus(peer.device_id, True, 4.0)
        app._reorder_cards()
        app.update()
        tiles = {node["id"]: node for node in app.device_tiles.nodes}
        assert tiles["*"]["name"] == "Alle enheder"  # two devices: an "all" tile first
        assert sorted(n["name"] for k, n in tiles.items() if k != "*") == ["Bærbar", "Mobil"]
        assert all(n["sub"] == "Wi-Fi · 4 ms" for k, n in tiles.items() if k != "*")

        app._tile_pick(peers[1].device_id)  # a click on a tile
        assert app.selected_id == peers[1].device_id
        eyebrow, title, status, _dot, _hint = app.hero._words
        assert (eyebrow, title) == ("SEND TIL", "BÆRBAR")
        assert status.startswith("Online")
        assert [n["id"] for n in app.device_tiles.nodes if n["selected"]] == [peers[1].device_id]
        assert app.hero_send._text == "SEND FILER"

        app._tile_pick("*")
        assert app._all_selected() and app.hero._words[1] == "ALLE ENHEDER"

        app.transfers["t"] = TransferState("t", "ferie.mp4", "send", "Bærbar", total=10, sent=4)
        app._update_transfer_badge()
        assert app.hero.actor.busy  # the monkey hops while files move
        sub = {n["id"]: n["sub"] for n in app.device_tiles.nodes}
        assert sub[peers[1].device_id] == "Sender …"
        assert app.device_tiles._pulse_after is not None  # its tile breathes blue
        app.device_tiles._pulse()
        app.hero._animate()  # one frame: embers drift, the monkey moves
        app.transfers["t"].status = "done"
        app._update_transfer_badge()
        assert app.hero.actor.gesture == "hops"  # a happy hop when the send has landed
        app.device_tiles._pulse()
        assert app.device_tiles._pulse_after is None  # the pulse stops with the send
        app.show_page("transfers")  # the title slides in
        app.update()
        title = app._page_headers["transfers"].find_withtag("page-title")
        assert title and app._page_headers["transfers"].itemcget(title[0], "text") == "OVERFØRSLER"
        assert len(app.hero._sparks) == 18  # and a ring of sparks
        for _ in range(25):
            app.hero._animate_sparks()
        assert app.hero._sparks == [] and not app.hero.find_withtag("spark")
        assert not app.hero.actor.busy
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_send_page_first_run_offers_to_connect() -> None:
    app = _new_app()
    try:
        app.update()
        assert app.hero._words[:2] == ("KOM I GANG", "FORBIND DIN TELEFON")
        assert app.hero_send._text == "FORBIND NY ENHED"
        opened = []
        app.show_qr_pairing = lambda: opened.append(True)
        app.hero_send.command()
        assert opened == [True]
        assert [n["id"] for n in app.device_tiles.nodes] == []  # only the "+" tile
    finally:
        app.close()


def test_monkey_actor_hops_grins_points_and_nods() -> None:
    import tkinter as tk

    from h4xtor_share.ui_kit import MonkeyActor

    try:
        root = tk.Tk()
    except tk.TclError as error:
        pytest.skip(f"Tk unavailable: {error}".splitlines()[0])
    try:
        canvas = tk.Canvas(root, width=300, height=300)
        actor = MonkeyActor(canvas, "m")
        actor.place(150, 150, 120)
        head_top = canvas.bbox("m")[1]

        def frames(count: int) -> None:
            for _ in range(count):
                actor.tick()

        arm = canvas.find_withtag("m-arm")[0]
        assert canvas.itemcget(arm, "state") == "hidden"
        actor.point()
        frames(4)
        assert canvas.itemcget(arm, "state") == "normal"  # the arm is out
        frames(len(actor.POINT))
        assert canvas.itemcget(arm, "state") == "hidden" and actor.gesture == ""

        mouth = canvas.find_withtag("m-mouth")[0]
        ear = canvas.find_withtag("m-ear")[0]
        ear_height = canvas.coords(ear)[3] - canvas.coords(ear)[1]
        actor.grin()
        frames(3)
        assert canvas.itemcget(mouth, "style") == "chord"  # mouth open
        assert canvas.coords(ear)[3] - canvas.coords(ear)[1] > ear_height * 1.2  # ears up
        frames(len(actor.GRIN))
        assert canvas.itemcget(mouth, "style") == "arc"
        assert abs(canvas.coords(ear)[3] - canvas.coords(ear)[1] - ear_height) < 0.01

        actor.nod()
        frames(3)
        assert canvas.bbox("m")[1] > head_top + 4  # head dips
        frames(len(actor.NOD))

        actor.set_busy(True)
        tops = []
        for _ in range(14):
            actor.tick()
            tops.append(canvas.bbox("m")[1])
        assert min(tops) < head_top - 8  # off the ground
        actor.set_busy(False)
        frames(30)
        assert abs(canvas.bbox("m")[1] - head_top) <= 3  # back on the ground (breathing only)
    finally:
        root.destroy()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_menu_groups_and_connections_page() -> None:
    app = _new_app()
    try:
        keys = [key for key, _icon, _label in app.NAV_ITEMS]
        assert keys[:3] == ["share", "transfers", "clipboard"]
        assert "connections" in keys and "connections" in app.pages
        app.show_page("connections")
        assert app.active_page == "connections"
        assert app.direct_status.winfo_toplevel() is app
    finally:
        app.close()


@pytest.mark.skipif(not _can_build_ui(), reason="Tk/tkdnd display server unavailable")
def test_every_button_and_menu_entry_runs(tmp_path, monkeypatch) -> None:
    """Press every button on every page (and in the dialogs they open) and run every
    entry of the menus they show: none may raise. Pickers return nothing."""
    import time
    import tkinter as tk
    import tkinter.filedialog as filedialog

    from h4xtor_share import app as app_module
    from h4xtor_share.models import TransferProgress
    from h4xtor_share.ui_kit import Button

    for name in ("askopenfilenames", "askopenfilename", "asksaveasfilename"):
        monkeypatch.setattr(filedialog, name, lambda **_k: "")
    monkeypatch.setattr(filedialog, "askdirectory", lambda **_k: "")
    monkeypatch.setattr(app_module, "open_path", lambda *_a, **_k: None)
    monkeypatch.setattr(app_module, "reveal_in_folder", lambda *_a, **_k: None)
    monkeypatch.setattr("webbrowser.open", lambda *_a, **_k: True)
    app, peers = _paired_app(1, tmp_path, monkeypatch, ("notifications", "sms", "remote-control"))
    problems: list[str] = []
    app.report_callback_exception = lambda *exc: problems.append(f"Tk callback: {exc[1]!r}")
    phone = peers[0]
    app._update_transfer(TransferProgress("a" * 32, "x.bin", 5, 10, "send", peer_name=phone.name))
    picture = tmp_path / "photo.jpg"
    picture.write_bytes(b"x" * 100)
    app.history.record_received_file(phone, picture.name, 100, str(picture))
    app.history.record_received_text(phone, "https://example.com")
    app.history.record_sent_file(phone, picture.name, 100, str(picture))
    app._refresh_history()

    def settle(seconds: float = 0.05) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.update()
            time.sleep(0.01)

    def dialogs() -> list[tk.Toplevel]:
        return [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]

    def buttons_in(widget: tk.Misc) -> list[Button]:
        found = []
        for child in widget.winfo_children():
            if isinstance(child, Button):
                found.append(child)
            found.extend(buttons_in(child))
        return found

    def press(button: Button, where: str) -> bool:
        if not button.winfo_exists() or not button.enabled or button.command is None:
            return False
        try:
            button.command()
        except Exception as error:  # noqa: BLE001 - collected and reported below
            problems.append(f"{where} {button._text or button._icon!r}: {error!r}")
        settle()
        return True

    menu_entries: list[str] = []

    def run_menu(menu: tk.Menu, _x: int, _y: int, _entry: str = "") -> None:
        last = menu.index("end")
        for index in range(0 if last is None else last + 1):
            if menu.type(index) != "command":
                continue
            label = menu.entrycget(index, "label")
            try:
                menu.invoke(index)
            except Exception as error:  # noqa: BLE001
                problems.append(f"menu {label!r}: {error!r}")
            menu_entries.append(label)
            settle()
            for dialog in dialogs():
                dialog.destroy()

    monkeypatch.setattr(tk.Menu, "tk_popup", run_menu)
    pressed = 0
    try:
        settle(0.3)
        for name in list(app.pages):
            app.show_page(name)
            settle()
            for button in buttons_in(app.pages[name]):
                label = button._text or button._icon
                if not press(button, f"{name}:"):
                    continue
                pressed += 1
                for dialog in dialogs():  # one level down: the dialog it opened
                    for inner in buttons_in(dialog):
                        pressed += press(inner, f"{name}: dialog from {label!r}:")
                        for extra in dialogs():
                            if extra is not dialog:
                                extra.destroy()
                for dialog in dialogs():
                    dialog.destroy()
                app.show_page(name)
        for button in buttons_in(app.sidebar):
            pressed += press(button, "menu:")
            for dialog in dialogs():
                dialog.destroy()
        settle(0.3)
    finally:
        monkeypatch.undo()
        app.close()
    assert not problems, "\n".join(problems)
    assert pressed > 40 and len(menu_entries) > 10, (pressed, menu_entries)
