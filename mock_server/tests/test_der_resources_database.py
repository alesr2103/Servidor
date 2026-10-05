import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mock_server import config
from mock_server.database import initialize_database
from mock_server.repositories import (
    DERResourceRepository,
    DeviceRepository,
)


class DERResourceDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = (
            Path(self.temp_dir.name) / "test.db"
        )

        self.database_patch = patch.object(
            config,
            "DATABASE_FILE",
            self.database_file,
        )
        self.data_dir_patch = patch.object(
            config,
            "DATA_DIR",
            Path(self.temp_dir.name),
        )

        self.database_patch.start()
        self.data_dir_patch.start()

        initialize_database()

        self.devices = DeviceRepository()
        self.resources = DERResourceRepository()

        self.device = self.devices.register_certificate(
            config.REGISTERED_CLIENT_CERT_FILE,
            "Cliente DER de prueba",
        )

    def tearDown(self):
        self.database_patch.stop()
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_save_and_get_der_status(self):
        body = (
            b'<DERStatus '
            b'xmlns="http://ieee.org/2030.5">'
            b'<readingTime>1700000000</readingTime>'
            b'</DERStatus>'
        )

        saved = self.resources.save(
            self.device.id,
            "DERStatus",
            body,
            source_timestamp=1700000000,
            received_at=1700000001,
        )

        self.assertEqual(
            saved.device_id,
            self.device.id,
        )
        self.assertEqual(
            saved.resource_type,
            "DERStatus",
        )
        self.assertEqual(saved.xml_body, body)
        self.assertEqual(
            saved.source_timestamp,
            1700000000,
        )

    def test_save_updates_existing_resource(self):
        first = (
            b'<DERStatus '
            b'xmlns="http://ieee.org/2030.5">'
            b'<readingTime>1</readingTime>'
            b'</DERStatus>'
        )
        second = (
            b'<DERStatus '
            b'xmlns="http://ieee.org/2030.5">'
            b'<readingTime>2</readingTime>'
            b'</DERStatus>'
        )

        original = self.resources.save(
            self.device.id,
            "DERStatus",
            first,
        )
        updated = self.resources.save(
            self.device.id,
            "DERStatus",
            second,
        )

        self.assertEqual(
            original.id,
            updated.id,
        )
        self.assertEqual(
            updated.xml_body,
            second,
        )
        self.assertEqual(
            len(
                self.resources.list_for_device(
                    self.device.id
                )
            ),
            1,
        )

    def test_multiple_resource_types(self):
        for resource_type in (
            "DERCapability",
            "DERSettings",
            "DERStatus",
            "DERAvailability",
        ):
            body = (
                f'<{resource_type} '
                f'xmlns="http://ieee.org/2030.5"/>'
            ).encode()

            self.resources.save(
                self.device.id,
                resource_type,
                body,
            )

        records = self.resources.list_for_device(
            self.device.id
        )

        self.assertEqual(len(records), 4)

    def test_invalid_resource_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.resources.save(
                self.device.id,
                "UnknownResource",
                b"<UnknownResource/>",
            )

    def test_delete_resource(self):
        self.resources.save(
            self.device.id,
            "DERStatus",
            (
                b'<DERStatus '
                b'xmlns="http://ieee.org/2030.5">'
                b'<readingTime>1</readingTime>'
                b'</DERStatus>'
            ),
        )

        deleted = self.resources.delete(
            self.device.id,
            "DERStatus",
        )

        self.assertTrue(deleted)
        self.assertIsNone(
            self.resources.get(
                self.device.id,
                "DERStatus",
            )
        )


if __name__ == "__main__":
    unittest.main()
