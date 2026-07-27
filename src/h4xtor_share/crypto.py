from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import ssl
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def ensure_certificate(config_directory: Path, device_name: str) -> tuple[Path, Path, str]:
    certificate_path = config_directory / "certificate.pem"
    key_path = config_directory / "private-key.pem"
    config_directory.mkdir(parents=True, exist_ok=True)

    if not certificate_path.exists() or not key_path.exists():
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "h4xtor-share"),
                x509.NameAttribute(NameOID.COMMON_NAME, device_name[:64]),
            ]
        )
        now = dt.datetime.now(dt.UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(
                x509.SubjectAlternativeName(
                    [
                        x509.DNSName("localhost"),
                        x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                    ]
                ),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )
        key_path.write_bytes(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        certificate_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))

    fingerprint = certificate_fingerprint(certificate_path)
    return certificate_path, key_path, fingerprint


def certificate_fingerprint(certificate_path: Path) -> str:
    certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
    return hashlib.sha256(certificate.public_bytes(serialization.Encoding.DER)).hexdigest()


def server_ssl_context(certificate_path: Path, key_path: Path) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certificate_path, key_path)
    return context
