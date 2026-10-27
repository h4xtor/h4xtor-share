from h4xtor_share.app import battery_text, phone_state_alert


def test_battery_text() -> None:
    assert battery_text(None) == ""
    assert battery_text({"battery": -1}) == ""  # the phone could not tell
    assert battery_text({"battery": 82, "charging": False}) == "82 %"
    assert battery_text({"battery": 40, "charging": True}) == "40 % ⚡"


def test_alerts_once_when_low_and_once_when_full() -> None:
    low = {"battery": 14, "charging": False}
    assert phone_state_alert("Mobil", None, low)[1] == "danger"  # already low at start
    assert phone_state_alert("Mobil", {"battery": 16, "charging": False}, low) == (
        "Mobil har kun 14 % strøm – sæt den til opladning", "danger")
    assert phone_state_alert("Mobil", low, {"battery": 12, "charging": False}) is None  # said
    assert phone_state_alert("Mobil", low, {"battery": 14, "charging": True}) is None
    unplugged = phone_state_alert("Mobil", {"battery": 14, "charging": True}, low)
    assert unplugged is not None  # unplugged while low: say it again

    full = {"battery": 100, "charging": True}
    assert phone_state_alert("Mobil", {"battery": 98, "charging": True}, full) == (
        "Mobil er fuldt opladet", "success")
    assert phone_state_alert("Mobil", full, full) is None  # once
    assert phone_state_alert("Mobil", None, full) is None  # not on the first look
    assert phone_state_alert("Mobil", {"battery": 60}, {"battery": 55}) is None
