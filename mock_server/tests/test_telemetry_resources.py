import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

from mock_server import config
from mock_server import xml_resources as xr


class TelemetryResourceTests(unittest.TestCase):
    def setUp(self):
        self.usage_point = SimpleNamespace(
            id=1,
            device_id=1,
            mrid="6688E18C000000030000D431",
            description=None,
            role_flags=9,
            service_category=0,
            post_rate=300,
            device_lfdi="0671c144d27dc9e612afe7dc6c79ec089ed3dcc5",
            status=1,
            xml_body=(
                f'<MirrorUsagePoint xmlns="{config.NAMESPACE}">'
                f'<mRID>6688E18C000000030000D431</mRID>'
                f'<roleFlags>09</roleFlags>'
                f'<serviceCategoryKind>0</serviceCategoryKind>'
                f'<status>1</status>'
                f'<deviceLFDI>0671c144d27dc9e612afe7dc6c79ec089ed3dcc5</deviceLFDI>'
                f'</MirrorUsagePoint>'
            ).encode(),
        )
        self.meter = self.make_meter(
            meter_id=2,
            mrid="6688E18C0000001B0000D431",
            description="Current (A)",
            reading_type="current_rms_A",
            phase="A",
            uom=5,
            multiplier=0,
            kind=0,
        )
        self.latest = self.make_reading(28, 2, 20, 1790972964)

        self.patches = (
            patch.object(xr.MIRROR_USAGE_POINT_REPOSITORY, "list_for_device", return_value=[]),
            patch.object(xr.MIRROR_USAGE_POINT_REPOSITORY, "get_by_id", return_value=None),
            patch.object(xr.MIRROR_METER_READING_REPOSITORY, "list_for_usage_point", return_value=[]),
            patch.object(xr.MIRROR_METER_READING_REPOSITORY, "get_by_id", return_value=None),
            patch.object(xr.METER_READING_REPOSITORY, "get_latest", return_value=None),
            patch.object(xr.METER_READING_REPOSITORY, "list_for_meter", return_value=[]),
        )
        self.mock_mup_list = self.patches[0].start()
        self.mock_mup_get = self.patches[1].start()
        self.mock_meter_list = self.patches[2].start()
        self.mock_meter_get = self.patches[3].start()
        self.mock_latest = self.patches[4].start()
        self.mock_reading_list = self.patches[5].start()

        for active_patch in self.patches:
            self.addCleanup(active_patch.stop)

    @staticmethod
    def make_meter(
        meter_id,
        mrid,
        description,
        reading_type,
        phase,
        uom,
        multiplier,
        kind,
    ):
        return SimpleNamespace(
            id=meter_id,
            usage_point_id=1,
            mrid=mrid,
            description=description,
            reading_type=reading_type,
            phase=phase,
            uom=uom,
            power_of_ten_multiplier=multiplier,
            flow_direction=1,
            accumulation_behaviour=None,
            commodity=1,
            data_qualifier=None,
            kind=kind,
        )

    @staticmethod
    def make_reading(reading_id, meter_id, value, reading_time):
        return SimpleNamespace(
            id=reading_id,
            meter_reading_id=meter_id,
            value=value,
            reading_time=reading_time,
            quality_flags=None,
        )

    def seven_meters(self):
        return [
            self.make_meter(1, "01", "Frequency (Hz)", "frequency", None, 33, 0, 0),
            self.make_meter(2, "02", "Current (A)", "current_rms_A", "A", 5, 0, 0),
            self.make_meter(3, "03", "Voltage (V)", "voltage_rms_A", "AN", 29, 0, 0),
            self.make_meter(4, "04", "Power Factor (PF)", "power_factor", None, 65, -3, 37),
            self.make_meter(5, "05", "Reactive Power (Var)", "reactive_power", None, 63, 0, 37),
            self.make_meter(6, "06", "Apparent Power (VA)", "apparent_power", None, 61, 0, 37),
            self.make_meter(7, "07", "Real Power (W)", "active_power", None, 38, 0, 37),
        ]

    def test_empty_mirror_meter_reading_list(self):
        self.mock_mup_get.return_value = self.usage_point
        root = ET.fromstring(xr.mirror_meter_reading_list(1))
        self.assertEqual(root.tag, f"{{{config.NAMESPACE}}}MirrorMeterReadingList")
        self.assertEqual(root.get("href"), "/mup/1/mr")
        self.assertEqual(root.get("all"), "0")
        self.assertEqual(root.get("results"), "0")

    def test_mirror_meter_reading_list_contains_seven_definitions(self):
        self.mock_mup_get.return_value = self.usage_point
        self.mock_meter_list.return_value = self.seven_meters()
        root = ET.fromstring(xr.mirror_meter_reading_list(1))
        meters = root.findall(f"{{{config.NAMESPACE}}}MirrorMeterReading")
        self.assertEqual(len(meters), 7)
        self.assertEqual(root.get("all"), "7")
        self.assertEqual(root.get("results"), "7")
        descriptions = [
            meter.find(f"{{{config.NAMESPACE}}}description").text
            for meter in meters
        ]
        self.assertEqual(
            descriptions,
            [
                "Frequency (Hz)",
                "Current (A)",
                "Voltage (V)",
                "Power Factor (PF)",
                "Reactive Power (Var)",
                "Apparent Power (VA)",
                "Real Power (W)",
            ],
        )

    def test_individual_meter_contains_latest_reading_and_type(self):
        self.mock_mup_get.return_value = self.usage_point
        self.mock_meter_get.return_value = self.meter
        self.mock_latest.return_value = self.latest
        root = ET.fromstring(xr.mirror_meter_reading_by_id(1, 2))
        self.assertEqual(root.tag, f"{{{config.NAMESPACE}}}MirrorMeterReading")
        self.assertEqual(root.get("href"), "/mup/1/mr/2")
        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}description").text, "Current (A)")
        self.assertEqual(root.find(f".//{{{config.NAMESPACE}}}phase").text, "128")
        self.assertEqual(root.find(f".//{{{config.NAMESPACE}}}uom").text, "5")
        self.assertEqual(root.find(f".//{{{config.NAMESPACE}}}value").text, "20")
        self.assertEqual(root.find(f".//{{{config.NAMESPACE}}}start").text, "1790972964")

    def test_reading_list_contains_history_in_chronological_order(self):
        self.mock_mup_get.return_value = self.usage_point
        self.mock_meter_get.return_value = self.meter
        self.mock_reading_list.return_value = [
            self.make_reading(28, 2, 20, 400),
            self.make_reading(21, 2, 20, 300),
            self.make_reading(14, 2, 20, 200),
            self.make_reading(7, 2, 20, 100),
        ]
        root = ET.fromstring(xr.meter_reading_list(1, 2, limit=100))
        readings = root.findall(f"{{{config.NAMESPACE}}}Reading")
        starts = [
            reading.find(f"{{{config.NAMESPACE}}}timePeriod/{{{config.NAMESPACE}}}start").text
            for reading in readings
        ]
        self.assertEqual(starts, ["100", "200", "300", "400"])
        self.assertEqual(root.get("all"), "4")
        self.assertEqual(root.get("results"), "4")
        self.mock_reading_list.assert_called_once_with(2, limit=100)

    def test_reading_list_passes_limit_to_repository(self):
        self.mock_mup_get.return_value = self.usage_point
        self.mock_meter_get.return_value = self.meter
        self.mock_reading_list.return_value = [
            self.make_reading(28, 2, 20, 400),
            self.make_reading(21, 2, 20, 300),
        ]
        root = ET.fromstring(xr.meter_reading_list(1, 2, limit=2))
        readings = root.findall(f"{{{config.NAMESPACE}}}Reading")
        self.assertEqual(len(readings), 2)
        self.mock_reading_list.assert_called_once_with(2, limit=2)

    def test_unknown_usage_point_returns_none(self):
        self.mock_mup_get.return_value = None
        self.assertIsNone(xr.mirror_meter_reading_list(999))
        self.assertIsNone(xr.mirror_meter_reading_by_id(999, 2))
        self.assertIsNone(xr.meter_reading_list(999, 2))

    def test_unknown_meter_returns_none(self):
        self.mock_mup_get.return_value = self.usage_point
        self.mock_meter_get.return_value = None
        self.assertIsNone(xr.mirror_meter_reading_by_id(1, 999))
        self.assertIsNone(xr.meter_reading_list(1, 999))

    def test_meter_from_another_usage_point_returns_none(self):
        self.mock_mup_get.return_value = self.usage_point
        self.mock_meter_get.return_value = SimpleNamespace(
            **{**self.meter.__dict__, "usage_point_id": 2}
        )
        self.assertIsNone(xr.mirror_meter_reading_by_id(1, 2))
        self.assertIsNone(xr.meter_reading_list(1, 2))

    def test_usage_point_from_another_device_returns_none(self):
        self.mock_mup_get.return_value = SimpleNamespace(
            **{**self.usage_point.__dict__, "device_id": 2}
        )
        self.assertIsNone(xr.mirror_meter_reading_list(1))
        self.assertIsNone(xr.mirror_meter_reading_by_id(1, 2))
        self.assertIsNone(xr.meter_reading_list(1, 2))


if __name__ == "__main__":
    unittest.main()
