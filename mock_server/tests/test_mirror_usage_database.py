import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mock_server import config
from mock_server.database import initialize_database
from mock_server.repositories import (
    DeviceRepository,
    MeterReadingRepository,
    MirrorMeterReadingRepository,
    MirrorUsagePointRepository,
)


class MirrorUsageDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_file = Path(self.temp_dir.name) / "test.db"
        self.database_patch = patch.object(config, "DATABASE_FILE", self.database_file)
        self.data_dir_patch = patch.object(config, "DATA_DIR", Path(self.temp_dir.name))
        self.database_patch.start()
        self.data_dir_patch.start()
        initialize_database()

        self.devices = DeviceRepository()
        self.usage_points = MirrorUsagePointRepository()
        self.meters = MirrorMeterReadingRepository()
        self.readings = MeterReadingRepository()
        self.device = self.devices.register_certificate(
            config.REGISTERED_CLIENT_CERT_FILE,
            "Cliente DER de telemetria",
        )
        self.usage_point = self.usage_points.save(
            device_id=self.device.id,
            mrid="AA00000000000001",
            description="Mediciones DER",
            role_flags=9,
            service_category=0,
            post_rate=60,
            device_lfdi=self.device.lfdi,
            status=1,
            xml_body=b'<MirrorUsagePoint xmlns="http://ieee.org/2030.5"/>',
            created_at=100,
        )

    def tearDown(self):
        self.database_patch.stop()
        self.data_dir_patch.stop()
        self.temp_dir.cleanup()

    def save_meter(self, mrid="BB00000000000001", reading_type="current_rms_A", uom=5, multiplier=-2, phase="A"):
        return self.meters.save(
            usage_point_id=self.usage_point.id,
            mrid=mrid,
            description=reading_type,
            reading_type=reading_type,
            phase=phase,
            uom=uom,
            power_of_ten_multiplier=multiplier,
            flow_direction=1,
            accumulation_behaviour=12,
            commodity=1,
            data_qualifier=0,
            kind=0,
            reading_type_xml=b'<ReadingType xmlns="http://ieee.org/2030.5"/>',
            created_at=100,
        )

    def test_save_and_get_usage_point(self):
        loaded = self.usage_points.get_by_device_and_mrid(self.device.id, "aa00000000000001")
        self.assertEqual(loaded.id, self.usage_point.id)
        self.assertEqual(loaded.post_rate, 60)
        self.assertEqual(loaded.status, 1)

    def test_usage_point_updates_without_duplicate(self):
        updated = self.usage_points.save(
            device_id=self.device.id,
            mrid="AA00000000000001",
            description="Mediciones DER actualizadas",
            role_flags=9,
            service_category=0,
            post_rate=300,
            device_lfdi=self.device.lfdi,
            status=1,
            xml_body=b'<MirrorUsagePoint xmlns="http://ieee.org/2030.5"><postRate>300</postRate></MirrorUsagePoint>',
            created_at=200,
        )
        self.assertEqual(updated.id, self.usage_point.id)
        self.assertEqual(updated.post_rate, 300)
        self.assertEqual(self.usage_points.count_for_device(self.device.id), 1)

    def test_save_supported_meter_types(self):
        definitions = (
            ("BB00000000000001", "current_rms_A", 5, 0, "A"),
            ("BB00000000000002", "voltage_rms_A", 29, 0, "AN"),
            ("BB00000000000003", "voltage_current_phase_angle_A", 0, -1, "A"),
            ("BB00000000000004", "frequency", 33, 0, None),
            ("BB00000000000005", "active_power", 38, 0, None),
            ("BB00000000000006", "apparent_power", 61, 0, None),
            ("BB00000000000007", "reactive_power", 63, 0, None),
            ("BB00000000000008", "power_factor", 65, 0, None),
        )

        for definition in definitions:
            self.save_meter(*definition)

        meters = self.meters.list_for_usage_point(self.usage_point.id)

        self.assertEqual(len(meters), 8)
        self.assertEqual(
            [meter.reading_type for meter in meters],
            [
                "current_rms_A",
                "voltage_rms_A",
                "voltage_current_phase_angle_A",
                "frequency",
                "active_power",
                "apparent_power",
                "reactive_power",
                "power_factor",
            ],
        )

    def test_meter_definition_updates_without_duplicate(self):
        first = self.save_meter()
        updated = self.meters.save(
            usage_point_id=self.usage_point.id,
            mrid=first.mrid,
            description="Corriente RMS fase A actualizada",
            reading_type="current_rms_A",
            phase="A",
            uom=5,
            power_of_ten_multiplier=-3,
            kind=0,
            created_at=200,
        )
        self.assertEqual(first.id, updated.id)
        self.assertEqual(updated.power_of_ten_multiplier, -3)
        self.assertEqual(len(self.meters.list_for_usage_point(self.usage_point.id)), 1)

    def test_save_and_list_readings(self):
        meter = self.save_meter()
        self.readings.save(
            meter_reading_id=meter.id,
            value=1234,
            reading_time=1000,
            quality_flags=1,
            xml_body=b'<Reading xmlns="http://ieee.org/2030.5"><value>1234</value></Reading>',
            received_at=1001,
        )
        self.readings.save(
            meter_reading_id=meter.id,
            value=1250,
            reading_time=1060,
            quality_flags=1,
            xml_body=b'<Reading xmlns="http://ieee.org/2030.5"><value>1250</value></Reading>',
            received_at=1061,
        )
        readings = self.readings.list_for_meter(meter.id)
        self.assertEqual(len(readings), 2)
        self.assertEqual(readings[0].value, 1250)
        self.assertEqual(self.readings.get_latest(meter.id).reading_time, 1060)

    def test_negative_phase_angle_is_preserved(self):
        meter = self.save_meter(
            mrid="BB00000000000003",
            reading_type="voltage_current_phase_angle_A",
            uom=0,
            multiplier=-1,
            phase="A",
        )
        reading = self.readings.save(
            meter_reading_id=meter.id,
            value=-125,
            reading_time=1000,
            quality_flags=1,
            xml_body=b'<Reading xmlns="http://ieee.org/2030.5"><value>-125</value></Reading>',
            received_at=1001,
        )
        self.assertEqual(reading.value, -125)

    def test_invalid_reading_type_is_rejected(self):
        with self.assertRaises(ValueError):
            self.save_meter(reading_type="unknown")

    def test_invalid_multiplier_is_rejected(self):
        with self.assertRaises(ValueError):
            self.save_meter(multiplier=-10)

    def test_delete_old_readings(self):
        meter = self.save_meter()
        self.readings.save(meter.id, 100, 100, b"<Reading/>", received_at=100)
        self.readings.save(meter.id, 200, 200, b"<Reading/>", received_at=200)
        deleted = self.readings.delete_older_than(150)
        self.assertEqual(deleted, 1)
        self.assertEqual(len(self.readings.list_for_meter(meter.id)), 1)

    def test_reading_limit_is_applied(self):
        meter = self.save_meter()

        for index in range(5):
            self.readings.save(
                meter_reading_id=meter.id,
                value=20 + index,
                reading_time=100 + index,
                xml_body=b"<Reading/>",
                received_at=100 + index,
            )

        records = self.readings.list_for_meter(meter.id, limit=2)
        self.assertEqual(len(records), 2)
        self.assertEqual([record.value for record in records], [24, 23])

    def test_reading_limit_is_applied(self):
        meter = self.save_meter()

        for index in range(5):
            self.readings.save(
                meter_reading_id=meter.id,
                value=20 + index,
                reading_time=100 + index,
                xml_body=b"<Reading/>",
                received_at=100 + index,
            )

        records = self.readings.list_for_meter(meter.id, limit=2)
        self.assertEqual(len(records), 2)
        self.assertEqual([record.value for record in records], [24, 23])

    def test_zero_reading_limit_is_rejected(self):
        meter = self.save_meter()

        with self.assertRaises(ValueError):
            self.readings.list_for_meter(meter.id, limit=0)

    def test_negative_reading_limit_is_rejected(self):
        meter = self.save_meter()

        with self.assertRaises(ValueError):
            self.readings.list_for_meter(meter.id, limit=-1)

    def test_non_numeric_reading_limit_is_rejected(self):
        meter = self.save_meter()

        with self.assertRaises(ValueError):
            self.readings.list_for_meter(meter.id, limit="abc")


if __name__ == "__main__":
    unittest.main()
