"""Cálculo y validación de identidad IEEE 2030.5."""

import base64
from dataclasses import dataclass
import hashlib
from pathlib import Path


LFDI_LENGTH = 20


@dataclass(frozen=True)
class DeviceIdentity:
    lfdi: bytes
    sfdi: int
    fingerprint_sha256: str

    @property
    def lfdi_hex(self):
        return self.lfdi.hex()


def calculate_check_digit(value):
    digit_sum = 0
    remaining = value

    while remaining:
        digit_sum += remaining % 10
        remaining //= 10

    return (10 - (digit_sum % 10)) % 10


def calculate_sfdi(lfdi):
    if len(lfdi) != LFDI_LENGTH:
        raise ValueError(
            f"El LFDI debe contener {LFDI_LENGTH} bytes"
        )

    first_five_bytes = int.from_bytes(
        lfdi[:5],
        byteorder="big",
    )

    truncated_value = first_five_bytes >> 4
    check_digit = calculate_check_digit(truncated_value)

    return truncated_value * 10 + check_digit


def identity_from_certificate_bytes(certificate_bytes):
    if not certificate_bytes:
        raise ValueError(
            "El certificado no puede estar vacío"
        )

    digest = hashlib.sha256(certificate_bytes).digest()

    lfdi = digest[:LFDI_LENGTH]
    sfdi = calculate_sfdi(lfdi)

    fingerprint = ":".join(
        f"{byte:02x}"
        for byte in digest
    )

    return DeviceIdentity(
        lfdi=lfdi,
        sfdi=sfdi,
        fingerprint_sha256=fingerprint,
    )


def load_certificate_der(path):
    certificate_path = Path(path)
    certificate_data = certificate_path.read_bytes()

    if b"-----BEGIN CERTIFICATE-----" not in certificate_data:
        return certificate_data

    encoded_lines = []

    inside_certificate = False

    for line in certificate_data.splitlines():
        line = line.strip()

        if line == b"-----BEGIN CERTIFICATE-----":
            inside_certificate = True
            continue

        if line == b"-----END CERTIFICATE-----":
            break

        if inside_certificate and line:
            encoded_lines.append(line)

    if not encoded_lines:
        raise ValueError(
            f"Certificado PEM vacío o inválido: "
            f"{certificate_path}"
        )

    try:
        return base64.b64decode(
            b"".join(encoded_lines),
            validate=True,
        )
    except ValueError as exc:
        raise ValueError(
            f"Certificado PEM inválido: "
            f"{certificate_path}"
        ) from exc


def identity_from_certificate_file(path):
    certificate_der = load_certificate_der(path)

    return identity_from_certificate_bytes(
        certificate_der
    )
