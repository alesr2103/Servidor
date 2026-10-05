import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mock_server import config
from mock_server.database import initialize_database
from mock_server.repositories import (
    ControlResponseRepository,
    DeviceRepository,
)


class ControlResponseDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = Path(self.temp_dir.name) / "test.db"
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
        self.responses = ControlResponseRepository()
        self.device = self.devices.register_certificate(
            config.REGISTERED_CLIENT_CERT_FILE,
            "Cliente DER de respuestas",
        )

    def tearDown(self):
        self.database_patch.stop()
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_save_and_get_response(self):
        body = (
            b'<DERControlResponse '
            b'xmlns="http://ieee.org/2030.5">'
            b'<createdDateTime>1700000000</createdDateTime>'
            b'<endDeviceLFDI>00112233445566778899'
            b'aabbccddeeff00112233</endDeviceLFDI>'
            b'<status>1</status>'
            b'<subject>04</subject>'
            b'</DERControlResponse>'
        )

        response = self.responses.save(
            device_id=self.device.id,
            response_type="DERControlResponse",
            subject="04",
            response_status=1,
            created_datetime=1700000000,
            xml_body=body,
            received_at=1700000001,
        )

        self.assertEqual(response.device_id, self.device.id)
        self.assertEqual(
            response.response_type,
            "DERControlResponse",
        )
        self.assertEqual(response.subject, "04")
        self.assertEqual(response.response_status, 1)
        self.assertEqual(
            response.created_datetime,
            1700000000,
        )
        self.assertEqual(response.xml_body, body)
        self.assertEqual(response.received_at, 1700000001)

    def test_multiple_responses_for_same_subject(self):
        for status in (1, 2):
            self.responses.save(
                device_id=self.device.id,
                response_type="DERControlResponse",
                subject="04",
                response_status=status,
                created_datetime=1700000000 + status,
                xml_body=(
                    f'<DERControlResponse '
                    f'xmlns="http://ieee.org/2030.5">'
                    f'<createdDateTime>{1700000000 + status}'
                    f'</createdDateTime>'
                    f'<status>{status}</status>'
                    f'<subject>04</subject>'
                    f'</DERControlResponse>'
                ).encode(),
                received_at=1700000000 + status,
            )

        responses = self.responses.list_for_subject("04")

        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0].response_status, 2)
        self.assertEqual(responses[1].response_status, 1)

    def test_list_for_device(self):
        self.responses.save(
            device_id=self.device.id,
            response_type="Response",
            xml_body=(
                b'<Response '
                b'xmlns="http://ieee.org/2030.5"/>'
            ),
            received_at=100,
        )
        self.responses.save(
            device_id=self.device.id,
            response_type="DERControlResponse",
            subject="04",
            xml_body=(
                b'<DERControlResponse '
                b'xmlns="http://ieee.org/2030.5"/>'
            ),
            received_at=200,
        )

        responses = self.responses.list_for_device(
            self.device.id
        )

        self.assertEqual(len(responses), 2)
        self.assertEqual(
            responses[0].response_type,
            "DERControlResponse",
        )

    def test_invalid_response_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.responses.save(
                device_id=self.device.id,
                response_type="UnknownResponse",
                xml_body=b"<UnknownResponse/>",
            )

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            self.responses.save(
                device_id=self.device.id,
                response_type="DERControlResponse",
                response_status=300,
                xml_body=(
                    b'<DERControlResponse '
                    b'xmlns="http://ieee.org/2030.5"/>'
                ),
            )

    def test_delete_older_than(self):
        self.responses.save(
            device_id=self.device.id,
            response_type="Response",
            xml_body=(
                b'<Response '
                b'xmlns="http://ieee.org/2030.5"/>'
            ),
            received_at=100,
        )
        self.responses.save(
            device_id=self.device.id,
            response_type="Response",
            xml_body=(
                b'<Response '
                b'xmlns="http://ieee.org/2030.5"/>'
            ),
            received_at=200,
        )

        deleted = self.responses.delete_older_than(150)

        self.assertEqual(deleted, 1)
        self.assertEqual(self.responses.count(), 1)


if __name__ == "__main__":
    unittest.main()
