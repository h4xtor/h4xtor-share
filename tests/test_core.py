from __future__ import annotations

from pathlib import Path

import pytest

from h4xtor_share.config import Config
from h4xtor_share.crypto import certificate_fingerprint, ensure_certificate
from h4xtor_share.server import safe_file_name, unique_destination


def test_safe_file_name_removes_path_components() -> None:
    assert safe_file_name("../../payload.bin") == "payload.bin"
    assert safe_file_name(r"C:\temp\payload.bin") == "payload.bin"


@pytest.mark.parametrize("value", ["", ".", "..", "\x00"])
def test_safe_file_name_rejects_invalid_names(value: str) -> None:
    with pytest.raises(ValueError):
        safe_file_name(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("report:2024.pdf", "report2024.pdf"),
        ("a<b>c?d*e|f\"g.txt", "abcdefg.txt"),
        ("notes;final (1).txt", "notes;final (1).txt"),
        ("file name . ", "file name"),
        ("CON", "_CON"),
        ("aux.log", "_aux.log"),
        ("NUL.txt", "_NUL.txt"),
        ("COM3", "_COM3"),
        ("LPT1 report.doc", "LPT1 report.doc"),
        (".hidden", ".hidden"),
    ],
)
def test_safe_file_name_is_cross_platform(value: str, expected: str) -> None:
    assert safe_file_name(value) == expected


def test_unique_destination_preserves_extension(tmp_path: Path) -> None:
    original = tmp_path / "archive.tar.gz"
    original.write_bytes(b"first")
    destination = unique_destination(tmp_path, original.name)
    assert destination.name == "archive.tar (1).gz"


def test_config_persists_directional_trust(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = Config(path)
    config.trust_outbound_peer("peer-a", "send-token", "ab" * 32, "Laptop")
    config.trust_inbound_peer("peer-a", "receive-token", "Laptop")

    restored = Config(path)
    assert restored.outbound_credentials("peer-a") == ("send-token", "ab" * 32)
    assert restored.validate_inbound_token("peer-a", "receive-token")
    assert not restored.validate_inbound_token("peer-a", "incorrect")


def test_certificate_is_reused_and_fingerprint_is_stable(tmp_path: Path) -> None:
    certificate, key, first = ensure_certificate(tmp_path, "Device")
    second_certificate, second_key, second = ensure_certificate(tmp_path, "Device")
    assert certificate == second_certificate
    assert key == second_key
    assert first == second
    assert certificate_fingerprint(certificate) == first
