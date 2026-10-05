import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mock_server import config
from mock_server.database import initialize_database
from mock_server.repositories import AuditEventRepository, DeviceRepository


class AuditDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = Path(self.temp_dir.name) / "test.db"
        self.database_patch = patch.object(config, "DATABASE_FILE", self.database_file)
        self.data_dir_patch = patch.object(config, "DATA_DIR", Path(self.temp_dir.name))
        self.database_patch.start()
        self.data_dir_patch.start()
        initialize_database()
        self.devices = DeviceRepository()
        self.audit = AuditEventRepository()
        self.device = self.devices.register_certificate(
            config.REGISTERED_CLIENT_CERT_FILE,
            "Cliente DER de auditoria",
        )

    def tearDown(self):
        self.database_patch.stop()
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_save_and_get_event(self):
        event = self.audit.save(
            device_id=self.device.id,
            event_category="resource",
            event_type="resource_updated",
            severity="info",
            http_method="PUT",
            route="/edev/1/der/1/ders",
            http_status=200,
            resource_type="DERStatus",
            source_ip="127.0.0.1",
            details="Recurso DER actualizado",
            created_at=1700000000,
        )

        self.assertEqual(event.device_id, self.device.id)
        self.assertEqual(event.event_type, "resource_updated")
        self.assertEqual(event.http_status, 200)
        self.assertEqual(event.created_at, 1700000000)

    def test_event_without_device(self):
        event = self.audit.save(
            event_category="security",
            event_type="tls_alert",
            severity="warning",
            source_ip="127.0.0.1",
        )

        self.assertIsNone(event.device_id)

    def test_list_for_device(self):
        self.audit.save(
            device_id=self.device.id,
            event_category="resource",
            event_type="resource_updated",
            http_status=200,
            created_at=1700000000,
        )
        self.audit.save(
            device_id=self.device.id,
            event_category="validation",
            event_type="xsd_validation_failed",
            severity="warning",
            http_status=400,
            created_at=1700000001,
        )

        events = self.audit.list_for_device(self.device.id)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].event_type, "xsd_validation_failed")

    def test_list_errors(self):
        self.audit.save(
            event_category="resource",
            event_type="resource_updated",
            http_status=200,
        )
        self.audit.save(
            event_category="validation",
            event_type="xsd_validation_failed",
            severity="warning",
            http_status=400,
        )

        errors = self.audit.list_errors()

        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].event_type, "xsd_validation_failed")

    def test_subject_is_preserved(self):
        event = self.audit.save(
            device_id=self.device.id,
            event_category="control",
            event_type="control_response_received",
            subject="04",
            http_status=201,
        )

        self.assertEqual(event.subject, "04")

    def test_delete_older_than(self):
        self.audit.save(
            event_category="system",
            event_type="old_event",
            created_at=100,
        )
        self.audit.save(
            event_category="system",
            event_type="current_event",
            created_at=200,
        )

        deleted = self.audit.delete_older_than(150)

        self.assertEqual(deleted, 1)
        self.assertEqual(self.audit.count(), 1)
        self.assertEqual(
            self.audit.list_recent()[0].event_type,
            "current_event",
        )

    def test_invalid_severity_is_rejected(self):
        with self.assertRaises(ValueError):
            self.audit.save(
                event_category="system",
                event_type="invalid_event",
                severity="unknown",
            )


if __name__ == "__main__":
    unittest.main()
