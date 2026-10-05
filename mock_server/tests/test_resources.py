import unittest
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

from mock_server import config
from mock_server import xml_resources as xr
from mock_server.store import STORE

class ResourceTests(unittest.TestCase):
    def setUp(self):
        STORE.reset()

        with STORE.lock:
            STORE.registration_time = 1700000000
            STORE.lfdi_hex = "0671c144d27dc9e612afe7dc6c79ec089ed3dcc5"
            STORE.sfdi = 17298934539

        patches = (
            patch.object(xr.DER_RESOURCE_REPOSITORY, "get", return_value=None),
            patch.object(xr.DER_PROGRAM_REPOSITORY, "get_active_for_device", return_value=None),
            patch.object(xr.DEFAULT_DER_CONTROL_REPOSITORY, "get_for_program", return_value=None),
            patch.object(xr.DER_CONTROL_REPOSITORY, "list_applicable", return_value=[]),
            patch.object(xr.DER_CONTROL_REPOSITORY, "get_by_id", return_value=None),
            patch.object(xr.CONTROL_RESPONSE_REPOSITORY, "list_for_device", return_value=[]),
            patch.object(xr.CONTROL_RESPONSE_REPOSITORY, "get_by_id", return_value=None),        
            patch.object(xr.MIRROR_USAGE_POINT_REPOSITORY, "list_for_device", return_value=[]),
            patch.object(xr.MIRROR_USAGE_POINT_REPOSITORY, "get_by_id", return_value=None), 
            )

        self.mock_der_resource_get = patches[0].start()
        self.mock_program_get = patches[1].start()
        self.mock_default_get = patches[2].start()
        self.mock_control_list = patches[3].start()
        self.mock_control_get = patches[4].start()
        self.mock_response_list = patches[5].start()
        self.mock_response_get = patches[6].start()
        self.mock_mup_list = patches[-2].start()
        self.mock_mup_get = patches[-1].start()

        for active_patch in patches:
            self.addCleanup(active_patch.stop)
    def test_all_resources_are_well_formed(self):
        for path, generator in xr.RESOURCES.items():
            with self.subTest(path=path):
                body = generator()
                if body is not None:
                    ET.fromstring(body)

    def test_default_control_has_no_connect_order(self):
        body = xr.default_control().decode()
        self.assertIn("DERControlBase", body)
        self.assertNotIn("opModConnect", body)

    def test_temporary_control_has_connect_true(self):
        body = xr.control().decode()
        self.assertIn("<opModConnect>true</opModConnect>", body)

    def test_persisted_program_is_used(self):
        self.mock_program_get.return_value = SimpleNamespace(
            id=10,
            mrid="A1",
            description="Programa persistente",
            version=3,
            primacy=2,
        )

        root = ET.fromstring(xr.program())
        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}mRID").text, "A1")
        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}description").text, "Programa persistente")
        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}version").text, "3")
        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}primacy").text, "2")

    def test_persisted_default_control_is_used(self):
        self.mock_program_get.return_value = SimpleNamespace(id=10)
        body = (
            f'<DefaultDERControl xmlns="{config.NAMESPACE}">'
            f'<mRID>A2</mRID>'
            f'<description>Control persistente</description>'
            f'<version>1</version>'
            f'<DERControlBase/>'
            f'</DefaultDERControl>'
        ).encode()
        self.mock_default_get.return_value = SimpleNamespace(control_xml=body)

        root = ET.fromstring(xr.default_control())
        self.assertEqual(root.get("href"), "/edev/1/fsa/1/derp/1/dderc")
        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}mRID").text, "A2")

    def test_persisted_control_is_used(self):
        now = 1700000000
        self.mock_program_get.return_value = SimpleNamespace(id=10)
        self.mock_control_list.return_value = [
            SimpleNamespace(
                id=20,
                mrid="A3",
                description="Control persistente",
                version=1,
                creation_time=now - 10,
                start_time=now + 60,
                duration=120,
                control_status="scheduled",
                control_xml=(
                    f'<DERControl xmlns="{config.NAMESPACE}">'
                    f'<DERControlBase><opModConnect>true</opModConnect></DERControlBase>'
                    f'</DERControl>'
                ).encode(),
                is_terminal=False,
                end_time=now + 180,
            )
        ]

        with patch("mock_server.xml_resources.time.time", return_value=now):
            root = ET.fromstring(xr.control())

        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}mRID").text, "A3")
        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}EventStatus/{{{config.NAMESPACE}}}currentStatus").text, "0")
        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}DERControlBase/{{{config.NAMESPACE}}}opModConnect").text, "true")

    def test_persisted_control_list_can_be_empty(self):
        self.mock_program_get.return_value = SimpleNamespace(id=10)
        self.mock_control_list.return_value = []

        root = ET.fromstring(xr.control_list())
        self.assertEqual(root.get("all"), "0")
        self.assertEqual(root.get("results"), "0")
        self.assertIsNone(xr.control())


    def test_expired_control(self):
        expired_time = STORE.control.end_time + 1

        with patch("mock_server.store.time.time", return_value=expired_time):
            self.assertIsNone(STORE.control.status())
            self.assertIsNone(xr.control())

            body = xr.control_list().decode()

            self.assertIn('all="0"', body)
            self.assertIn('results="0"', body)

    def test_end_device_contains_registration_link(self):
        root = ET.fromstring(xr.end_device_list())
        link = root.find(f".//{{{config.NAMESPACE}}}RegistrationLink")

        self.assertIsNotNone(link)
        self.assertEqual(link.get("href"), "/edev/1/rg")

    def test_registration_resource(self):
        root = ET.fromstring(xr.registration())

        self.assertEqual(root.tag, f"{{{config.NAMESPACE}}}Registration")
        self.assertEqual(root.get("href"), "/edev/1/rg")
        self.assertEqual(root.get("pollRate"), str(config.REGISTRATION_POLL_RATE))

        registration_time = root.find(f"{{{config.NAMESPACE}}}dateTimeRegistered")

        self.assertIsNotNone(registration_time)
        self.assertEqual(registration_time.text, str(STORE.registration_time))

        pin = root.find(f"{{{config.NAMESPACE}}}pIN")

        self.assertIsNotNone(pin)
        self.assertEqual(pin.text, str(config.REGISTRATION_PIN))

    def test_registration_route_exists(self):
        self.assertIn("/edev/1/rg", xr.RESOURCES)
        self.assertIs(xr.RESOURCES["/edev/1/rg"], xr.registration)

    def test_end_device_element_order(self):
        root = ET.fromstring(xr.end_device_list())
        end_device = root.find(f"{{{config.NAMESPACE}}}EndDevice")

        self.assertIsNotNone(end_device)

        child_names = [element.tag.rsplit("}", 1)[-1] for element in end_device]

        self.assertEqual(
            child_names,
            [
                "DERListLink",
                "lFDI",
                "sFDI",
                "changedTime",
                "FunctionSetAssignmentsListLink",
                "RegistrationLink",
            ],)


    def test_der_contains_monitoring_links(self):
        root = ET.fromstring(xr.der())
        names = [child.tag.rsplit("}", 1)[-1] for child in root]

        self.assertEqual(
            names,
            [
                "DERAvailabilityLink",
                "DERCapabilityLink",
                "DERSettingsLink",
                "DERStatusLink",
            ],
        )

    def test_der_capability_required_fields(self):
        root = ET.fromstring(xr.der_capability())
        names = [child.tag.rsplit("}", 1)[-1] for child in root]

        self.assertEqual(names, ["modesSupported", "rtgA", "rtgW", "type"])

    def test_der_settings_required_fields(self):
        root = ET.fromstring(xr.der_settings())
        names = [child.tag.rsplit("}", 1)[-1] for child in root]

        self.assertEqual(names, ["setGradW", "setMaxW", "updatedTime"])

    def test_der_status_contains_reading_time(self):
        root = ET.fromstring(xr.der_status())
        names = [child.tag.rsplit("}", 1)[-1] for child in root]

        self.assertIn("readingTime", names)


    def test_der_availability_contains_reading_time(self):
        root = ET.fromstring(xr.der_availability())
        names = [child.tag.rsplit("}", 1)[-1] for child in root]

        self.assertIn("readingTime", names)

    def test_der_resources_return_persisted_xml(self):
        cases = (
            ("DERCapability", xr.der_capability),
            ("DERSettings", xr.der_settings),
            ("DERStatus", xr.der_status),
            ("DERAvailability", xr.der_availability),
        )

        for resource_type, generator in cases:
            with self.subTest(resource_type=resource_type):
                body = f'<{resource_type} xmlns="{config.NAMESPACE}"/>'.encode()
                self.mock_der_resource_get.return_value = SimpleNamespace(xml_body=body)

                self.assertEqual(generator(), body)
                self.mock_der_resource_get.assert_called_with(1, resource_type)

    def test_persisted_control_by_id(self):
        now = 1700000000
        record = SimpleNamespace(
            id=25,
            device_id=1,
            mrid="ABCDEF1234567890",
            description="Control individual",
            version=1,
            creation_time=now - 10,
            start_time=now + 60,
            duration=120,
            control_status="scheduled",
            control_xml=(
                f'<DERControl xmlns="{config.NAMESPACE}">'
                f'<DERControlBase><opModConnect>true</opModConnect></DERControlBase>'
                f'</DERControl>'
            ).encode(),
            is_terminal=False,
            end_time=now + 180,
        )
        self.mock_control_get.return_value = record

        with patch("mock_server.xml_resources.time.time", return_value=now):
            root = ET.fromstring(xr.control_by_id(25))

        self.mock_control_get.assert_called_with(25)
        self.assertEqual(root.get("href"), "/edev/1/fsa/1/derp/1/derc/25")
        self.assertEqual(root.find(f"{{{config.NAMESPACE}}}mRID").text, "ABCDEF1234567890")

    def test_unknown_control_by_id_returns_none(self):
        self.mock_control_get.return_value = None
        self.assertIsNone(xr.control_by_id(999))

    def test_expired_control_by_id_returns_none(self):
        now = 1700000000
        self.mock_control_get.return_value = SimpleNamespace(
            id=25,
            device_id=1,
            is_terminal=False,
            start_time=now - 200,
            duration=100,
            end_time=now - 100,
        )

        with patch("mock_server.xml_resources.time.time", return_value=now):
            self.assertIsNone(xr.control_by_id(25))

    def test_response_set_list(self):
        root = ET.fromstring(xr.response_set_list())
        self.assertEqual(root.tag, f"{{{config.NAMESPACE}}}ResponseSetList")
        self.assertEqual(root.get("all"), "1")
        response_set = root.find(f"{{{config.NAMESPACE}}}ResponseSet")
        self.assertIsNotNone(response_set)
        self.assertEqual(response_set.get("href"), "/rsps/1")

    def test_empty_response_list(self):
        root = ET.fromstring(xr.response_list())
        self.assertEqual(root.tag, f"{{{config.NAMESPACE}}}ResponseList")
        self.assertEqual(root.get("all"), "0")
        self.assertEqual(root.get("results"), "0")

    def test_persisted_response_list(self):
        body = (
            f'<DERControlResponse xmlns="{config.NAMESPACE}">'
            f'<createdDateTime>1700000000</createdDateTime>'
            f'<endDeviceLFDI>00112233445566778899aabbccddeeff00112233</endDeviceLFDI>'
            f'<status>1</status>'
            f'<subject>ABCDEF1234567890</subject>'
            f'</DERControlResponse>'
        ).encode()
        self.mock_response_list.return_value = [
            SimpleNamespace(id=20, device_id=1, xml_body=body)
        ]

        root = ET.fromstring(xr.response_list())
        response = root.find(f"{{{config.NAMESPACE}}}Response")
        self.assertIsNotNone(response)
        self.assertEqual(response.get("href"), "/rsps/1/rsp/20")
        self.assertEqual(response.find(f"{{{config.NAMESPACE}}}status").text, "1")
        self.assertEqual(response.find(f"{{{config.NAMESPACE}}}subject").text, "ABCDEF1234567890")

    def test_persisted_response_by_id(self):
        body = (
            f'<DERControlResponse xmlns="{config.NAMESPACE}">'
            f'<createdDateTime>1700000000</createdDateTime>'
            f'<endDeviceLFDI>00112233445566778899aabbccddeeff00112233</endDeviceLFDI>'
            f'<status>2</status>'
            f'<subject>ABCDEF1234567890</subject>'
            f'</DERControlResponse>'
        ).encode()
        self.mock_response_get.return_value = SimpleNamespace(
            id=20,
            device_id=1,
            xml_body=body,
        )

        root = ET.fromstring(xr.response_by_id(20))
        self.mock_response_get.assert_called_with(20)
        self.assertEqual(root.tag, f"{{{config.NAMESPACE}}}DERControlResponse")
        self.assertEqual(root.get("href"), "/rsps/1/rsp/20")

    def test_unknown_response_by_id_returns_none(self):
        self.mock_response_get.return_value = None
        self.assertIsNone(xr.response_by_id(999))

    def test_device_capability_contains_mup_link(self):
        root = ET.fromstring(xr.device_capability())
        link = root.find(f"{{{config.NAMESPACE}}}MirrorUsagePointListLink")
        self.assertIsNotNone(link)
        self.assertEqual(link.get("href"), "/mup")

    def test_empty_mirror_usage_point_list(self):
        root = ET.fromstring(xr.mirror_usage_point_list())
        self.assertEqual(root.tag, f"{{{config.NAMESPACE}}}MirrorUsagePointList")
        self.assertEqual(root.get("all"), "0")
        self.assertEqual(root.get("results"), "0")

    def test_end_device_contains_lfdi(self):
        root = ET.fromstring(xr.end_device_list())
        lfdi = root.find(f".//{{{config.NAMESPACE}}}lFDI")
        self.assertIsNotNone(lfdi)
        self.assertEqual(lfdi.text, STORE.lfdi_hex)

if __name__ == "__main__":
    unittest.main()
