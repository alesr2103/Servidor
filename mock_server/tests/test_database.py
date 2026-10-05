import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mock_server import config
from mock_server.database import initialize_database
from mock_server.repositories import DeviceRepository


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = Path(self.temp_dir.name) / "test.db"
        self.database_patch = patch.object(config, "DATABASE_FILE", self.database_file)
        self.data_dir_patch = patch.object(config, "DATA_DIR", Path(self.temp_dir.name))
        self.database_patch.start()
        self.data_dir_patch.start()
        initialize_database()
        self.repository = DeviceRepository()

    def tearDown(self):
        self.database_patch.stop()
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_register_reference_device(self):
        device = self.repository.register_certificate(config.REGISTERED_CLIENT_CERT_FILE, "Cliente de prueba")
        self.assertEqual(device.lfdi, "0671c144d27dc9e612afe7dc6c79ec089ed3dcc5")
        self.assertEqual(device.sfdi, 17298934539)
        self.assertTrue(device.is_authorized)

    def test_register_same_certificate_is_idempotent(self):
        first = self.repository.register_certificate(config.REGISTERED_CLIENT_CERT_FILE, "Cliente de prueba")
        second = self.repository.register_certificate(config.REGISTERED_CLIENT_CERT_FILE, "Cliente repetido")
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(self.repository.list_devices()), 1)

    def test_find_authorized_by_lfdi(self):
        device = self.repository.register_certificate(config.REGISTERED_CLIENT_CERT_FILE, "Cliente de prueba")
        found = self.repository.find_authorized_by_lfdi(device.lfdi)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, device.id)

    def test_blocked_device_is_not_authorized(self):
        device = self.repository.register_certificate(config.REGISTERED_CLIENT_CERT_FILE, "Cliente de prueba")
        self.repository.set_authorization_status(device.id, "blocked")
        self.assertIsNone(self.repository.find_authorized_by_lfdi(device.lfdi))

    def test_last_seen_is_updated(self):
        device = self.repository.register_certificate(config.REGISTERED_CLIENT_CERT_FILE, "Cliente de prueba")
        self.repository.update_last_seen(device.id, 1700000000)
        updated = self.repository.find_by_id(device.id)
        self.assertEqual(updated.last_seen, 1700000000)


    def test_device_can_be_reactivated(self):
        device = self.repository.register_certificate(config.REGISTERED_CLIENT_CERT_FILE, "Cliente de prueba")
        self.repository.set_authorization_status(device.id, "blocked")
        self.assertIsNone(self.repository.find_authorized_by_lfdi(device.lfdi))
        self.repository.set_authorization_status(device.id, "active")
        authorized = self.repository.find_authorized_by_lfdi(device.lfdi)
        self.assertIsNotNone(authorized)
        self.assertEqual(authorized.id, device.id)


if __name__ == "__main__":
    unittest.main()
