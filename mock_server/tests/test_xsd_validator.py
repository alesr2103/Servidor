""" Pruebas del validador """

import unittest

from mock_server.xsd_validator import SEP_XML_VALIDATOR, XSDValidationError


class XSDValidatorTests(unittest.TestCase):
    def test_valid_der_status(self):
        body = (
            b'<DERStatus xmlns="http://ieee.org/2030.5">'
            b'<readingTime>1700000000</readingTime>'
            b'</DERStatus>'
        )
        SEP_XML_VALIDATOR.validate(body)

    def test_missing_required_reading_time_is_rejected(self):
        body = b'<DERStatus xmlns="http://ieee.org/2030.5"/>'

        with self.assertRaises(XSDValidationError):
            SEP_XML_VALIDATOR.validate(body)

    def test_wrong_element_order_is_rejected(self):
        body = (
            b'<DERStatus xmlns="http://ieee.org/2030.5">'
            b'<readingTime>1700000000</readingTime>'
            b'<inverterStatus>'
            b'<dateTime>1700000000</dateTime>'
            b'<value>4</value>'
            b'</inverterStatus>'
            b'</DERStatus>'
        )

        with self.assertRaises(XSDValidationError):
            SEP_XML_VALIDATOR.validate(body)

    def test_wrong_namespace_is_rejected(self):
        body = (
            b'<DERStatus xmlns="urn:incorrect">'
            b'<readingTime>1700000000</readingTime>'
            b'</DERStatus>'
        )

        with self.assertRaises(XSDValidationError):
            SEP_XML_VALIDATOR.validate(body)


if __name__ == "__main__":
    unittest.main()
