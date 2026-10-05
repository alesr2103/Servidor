"""Pruebas del cálculo de identidad IEEE 2030.5."""

import hashlib
import unittest

from mock_server.identity import (
    LFDI_LENGTH,
    calculate_check_digit,
    calculate_sfdi,
    identity_from_certificate_bytes,
)


class TestIdentity(unittest.TestCase):
    def test_check_digit(self):
        value = 12345
        expected = 5

        self.assertEqual(
            calculate_check_digit(value),
            expected,
        )

    def test_identity_uses_sha256(self):
        certificate_bytes = b"certificado de prueba"

        identity = identity_from_certificate_bytes(
            certificate_bytes
        )

        expected_digest = hashlib.sha256(
            certificate_bytes
        ).digest()

        self.assertEqual(
            identity.lfdi,
            expected_digest[:LFDI_LENGTH],
        )

    def test_lfdi_has_twenty_bytes(self):
        identity = identity_from_certificate_bytes(
            b"otro certificado"
        )

        self.assertEqual(
            len(identity.lfdi),
            20,
        )

        self.assertEqual(
            len(identity.lfdi_hex),
            40,
        )

    def test_sfdi_contains_check_digit(self):
        identity = identity_from_certificate_bytes(
            b"certificado"
        )

        sfdi_base = identity.sfdi // 10
        check_digit = identity.sfdi % 10

        self.assertEqual(
            check_digit,
            calculate_check_digit(sfdi_base),
        )

    def test_empty_certificate_is_rejected(self):
        with self.assertRaises(ValueError):
            identity_from_certificate_bytes(b"")

    def test_invalid_lfdi_length_is_rejected(self):
        with self.assertRaises(ValueError):
            calculate_sfdi(b"muy corto")


if __name__ == "__main__":
    unittest.main()

