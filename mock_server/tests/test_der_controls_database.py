import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mock_server import config
from mock_server.database import initialize_database
from mock_server.repositories import (
    DefaultDERControlRepository,
    DERControlRepository,
    DERProgramRepository,
    DeviceRepository,
)


class DERControlsDatabaseTests(unittest.TestCase):
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
        self.programs = DERProgramRepository()
        self.defaults = DefaultDERControlRepository()
        self.controls = DERControlRepository()
        self.device = self.devices.register_certificate(
            config.REGISTERED_CLIENT_CERT_FILE,
            "Cliente DER de controles",
        )
        self.program = self.programs.save(
            device_id=self.device.id,
            mrid="02",
            description="Programa DER principal",
            version=1,
            primacy=0,
            created_at=100,
        )

    def tearDown(self):
        self.database_patch.stop()
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def create_control(self, mrid="04", start_time=200, duration=120):
        body = (
            f'<DERControl xmlns="{config.NAMESPACE}">'
            f'<mRID>{mrid}</mRID>'
            f'</DERControl>'
        ).encode()

        return self.controls.save(
            program_id=self.program.id,
            device_id=self.device.id,
            mrid=mrid,
            description="Control DER temporal",
            version=1,
            creation_time=100,
            start_time=start_time,
            duration=duration,
            control_xml=body,
            created_at=100,
        )

    def test_create_and_get_program(self):
        saved = self.programs.get_by_mrid("02")
        self.assertEqual(saved.id, self.program.id)
        self.assertEqual(saved.device_id, self.device.id)
        self.assertTrue(saved.active)
        self.assertEqual(
            self.programs.get_active_for_device(self.device.id).id,
            self.program.id,
        )

    def test_save_default_control_updates_without_duplicate(self):
        first = self.defaults.save(
            program_id=self.program.id,
            mrid="03",
            description="Control predeterminado",
            version=1,
            control_xml=b'<DefaultDERControl xmlns="http://ieee.org/2030.5"/>',
            created_at=100,
        )
        updated = self.defaults.save(
            program_id=self.program.id,
            mrid="03",
            description="Control predeterminado actualizado",
            version=2,
            control_xml=b'<DefaultDERControl xmlns="http://ieee.org/2030.5"><DERControlBase/></DefaultDERControl>',
            created_at=200,
        )

        self.assertEqual(first.id, updated.id)
        self.assertEqual(updated.version, 2)
        self.assertEqual(
            updated.description,
            "Control predeterminado actualizado",
        )

    def test_create_and_get_control(self):
        control = self.create_control()
        loaded = self.controls.get_by_mrid("04")
        self.assertEqual(loaded.id, control.id)
        self.assertEqual(loaded.control_status, "scheduled")
        self.assertEqual(loaded.end_time, 320)
        self.assertFalse(loaded.is_terminal)

    def test_list_applicable_controls(self):
        self.create_control("04", 200, 120)
        self.create_control("05", 500, 120)
        applicable = self.controls.list_applicable(
            self.device.id,
            current_time=250,
        )

        self.assertEqual(
            [control.mrid for control in applicable],
            ["04", "05"],
        )

    def test_update_status_by_mrid(self):
        self.create_control()
        updated = self.controls.update_status_by_mrid(
            "04",
            "received",
            updated_at=250,
        )

        self.assertEqual(updated.control_status, "received")
        self.assertEqual(updated.updated_at, 250)

    def test_cancel_control(self):
        self.create_control()
        cancelled = self.controls.cancel(
            "04",
            cancelled_at=250,
        )

        self.assertEqual(cancelled.control_status, "cancelled")
        self.assertEqual(cancelled.cancelled_at, 250)
        self.assertTrue(cancelled.is_terminal)

    def test_expire_due_controls(self):
        self.create_control("04", 100, 10)
        self.create_control("05", 200, 100)
        expired = self.controls.expire_due(current_time=150)

        self.assertEqual(expired, 1)
        self.assertEqual(
            self.controls.get_by_mrid("04").control_status,
            "expired",
        )
        self.assertEqual(
            self.controls.get_by_mrid("05").control_status,
            "scheduled",
        )

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            self.create_control()
            self.controls.update_status_by_mrid(
                "04",
                "unknown",
            )

    def test_terminal_control_cannot_be_cancelled(self):
        self.create_control()
        self.controls.update_status_by_mrid(
            "04",
            "completed",
        )

        with self.assertRaises(ValueError):
            self.controls.cancel("04")

    def test_response_status_received_updates_control(self):
        self.create_control()
        previous, updated, name = self.controls.apply_response_status("04", 1, updated_at=250)
        self.assertEqual(previous.control_status, "scheduled")
        self.assertEqual(updated.control_status, "received")
        self.assertEqual(name, "received")

    def test_response_status_started_updates_control(self):
        self.create_control()
        self.controls.apply_response_status("04", 1, updated_at=240)
        previous, updated, name = self.controls.apply_response_status("04", 2, updated_at=250)
        self.assertEqual(previous.control_status, "received")
        self.assertEqual(updated.control_status, "started")
        self.assertEqual(name, "started")

    def test_response_status_superseded_updates_control(self):
        self.create_control()
        previous, updated, name = self.controls.apply_response_status("04", 7, updated_at=250)
        self.assertEqual(previous.control_status, "scheduled")
        self.assertEqual(updated.control_status, "superseded")
        self.assertEqual(name, "superseded")
        self.assertTrue(updated.is_terminal)

    def test_unknown_subject_does_not_modify_controls(self):
        previous, updated, name = self.controls.apply_response_status("UNKNOWN", 1)
        self.assertIsNone(previous)
        self.assertIsNone(updated)
        self.assertEqual(name, "received")

    def test_repeated_response_does_not_regress_status(self):
        self.create_control()
        self.controls.apply_response_status("04", 2, updated_at=250)
        previous, updated, name = self.controls.apply_response_status("04", 1, updated_at=260)
        self.assertEqual(previous.control_status, "started")
        self.assertEqual(updated.control_status, "started")
        self.assertEqual(name, "received")

    def test_response_subject_is_case_insensitive(self):
        self.create_control("ABCDEF1234567890")
        previous, updated, name = self.controls.apply_response_status(
            "abcdef1234567890",
            1,
            updated_at=250,
        )

        self.assertEqual(previous.mrid, "ABCDEF1234567890")
        self.assertEqual(updated.control_status, "received")
        self.assertEqual(name, "received")

if __name__ == "__main__":
    unittest.main()
