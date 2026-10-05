"""Validación segura de recursos IEEE 2030.5 contra sep.xsd."""

import threading

from lxml import etree

from . import config


class XSDValidationError(ValueError):
    pass


class SEPXMLValidator:
    def __init__(self, schema_file=None):
        self.schema_file = schema_file or config.SEP_XSD_FILE
        self._schema = None
        self._lock = threading.RLock()

    def _load_schema(self):
        with self._lock:
            if self._schema is not None:
                return self._schema

            if not self.schema_file.is_file():
                raise RuntimeError(f"No existe el esquema XSD: {self.schema_file}")

            parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)
            document = etree.parse(str(self.schema_file), parser)
            self._schema = etree.XMLSchema(document)
            return self._schema

    def validate(self, xml_body):
        if not isinstance(xml_body, bytes) or not xml_body:
            raise XSDValidationError("El cuerpo XML está vacío")

        parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False)

        try:
            document = etree.fromstring(xml_body, parser)
        except etree.XMLSyntaxError as exc:
            raise XSDValidationError(f"XML inválido: {exc}") from exc

        schema = self._load_schema()

        with self._lock:
            if schema.validate(document):
                return

            error = schema.error_log.last_error
            detail = error.message if error is not None else "estructura no permitida"
            raise XSDValidationError(f"El XML no valida contra sep.xsd: {detail}")


SEP_XML_VALIDATOR = SEPXMLValidator()

