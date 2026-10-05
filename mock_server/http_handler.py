"""Capa HTTP del mock server."""

import logging
import re
import ssl
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import config
from .repositories import AUDIT_EVENT_REPOSITORY, CONTROL_RESPONSE_REPOSITORY, DER_CONTROL_REPOSITORY, DER_RESOURCE_REPOSITORY, DEVICE_REPOSITORY, METER_READING_REPOSITORY, MIRROR_METER_READING_REPOSITORY, MIRROR_USAGE_POINT_REPOSITORY
from .store import STORE
from .tls import get_peer_identity
from .xml_resources import RESOURCES, control_by_id, meter_reading_list, mirror_meter_reading_by_id, mirror_meter_reading_list, mirror_usage_point_by_id, response_by_id
from .xsd_validator import SEP_XML_VALIDATOR
from .metering_types import default_phase_for_type, reading_type_for_uom


from . import xml_resources as xr

logger = logging.getLogger("ieee2030.5.mock")

POST_ROUTES = {
    "/rsps": "process_response",
    "/rsps/1/rsp":"process_response",
    "/mup": "process_mirror_usage_point",
}

PUT_ROUTES = {
    "/edev/1/der/1/dera": ("DERAvailability", {"DERAvailability"}, "readingTime"),
    "/edev/1/der/1/dercap": ("DERCapability", {"DERCapability"}, None),
    "/edev/1/der/1/derg": ("DERSettings", {"DERSettings"}, "updatedTime"),
    "/edev/1/der/1/ders": ("DERStatus", {"DERStatus"}, "readingTime"),
}

ACCEPTED_XML_TYPES = {
    "application/sep+xml",
    "application/xml",
    "text/xml",
}

DEVICE_ROUTE_PATTERN = re.compile(r"^/edev/(\d+)(?:/|$)")

DER_CONTROL_ROUTE_PATTERN = re.compile(r"^/edev/(\d+)/fsa/(\d+)/derp/(\d+)/derc/(\d+)$")

FSA_ROUTE_PATTERN = re.compile(
    r"^/edev/(\d+)/fsa/(\d+)$"
)

DER_PROGRAM_LIST_ROUTE_PATTERN = re.compile(
    r"^/edev/(\d+)/fsa/(\d+)/derp$"
)

DER_PROGRAM_ROUTE_PATTERN = re.compile(
    r"^/edev/(\d+)/fsa/(\d+)/derp/(\d+)$"
)

DEFAULT_DER_CONTROL_ROUTE_PATTERN = re.compile(
    r"^/edev/(\d+)/fsa/(\d+)/derp/(\d+)/dderc$"
)

DER_CONTROL_LIST_ROUTE_PATTERN = re.compile(
    r"^/edev/(\d+)/fsa/(\d+)/derp/(\d+)/derc$"
)


RESPONSE_ROUTE_PATTERN = re.compile(r"^/rsps/(\d+)/rsp/(\d+)$")

MIRROR_USAGE_POINT_ROUTE_PATTERN = re.compile(r"^/mup/(\d+)$")

MIRROR_METER_READING_LIST_PATTERN = re.compile(r"^/mup/(\d+)/mr$")

MIRROR_METER_READING_ROUTE_PATTERN = re.compile(r"^/mup/(\d+)/mr/(\d+)$")

METER_READING_LIST_PATTERN = re.compile(r"^/mup/(\d+)/mr/(\d+)/r$")

class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    peer_identity = None
    peer_device = None

    def log_message(self, fmt, *args):
        logger.info("%s:%s | %s", self.client_address[0], self.client_address[1], fmt % args)

    def authenticate_client(self):
        self.peer_identity = None
        self.peer_device = None

        if not config.TLS_ENABLED:
            return

        certificate_der = self.connection.getpeercert(binary_form=True)

        if not certificate_der:
            if config.TLS_REQUIRE_CLIENT_CERTIFICATE:
                raise PermissionError("El cliente no presento un certificado")
            logger.info("Cliente conectado mediante TLS sin certificado cliente")
            return

        self.peer_identity = get_peer_identity(self.connection)
        logger.info(
            "Cliente TLS: version=%s cipher=%s fingerprint=%s lfdi=%s sfdi=%d",
            self.peer_identity["tls_version"],
            self.peer_identity["cipher"],
            self.peer_identity["fingerprint"],
            self.peer_identity["lfdi_hex"],
            self.peer_identity["sfdi"],
        )

        self.peer_device = DEVICE_REPOSITORY.find_authorized_by_lfdi(self.peer_identity["lfdi_hex"])

        if self.peer_device is None:
            registered_device = DEVICE_REPOSITORY.find_by_lfdi(self.peer_identity["lfdi_hex"])

            if registered_device is None:
                logger.warning(
                    "Dispositivo TLS valido, pero no registrado: lfdi=%s sfdi=%d fingerprint=%s",
                    self.peer_identity["lfdi_hex"],
                    self.peer_identity["sfdi"],
                    self.peer_identity["fingerprint"],
                )
                raise PermissionError("El certificado no corresponde a un EndDevice registrado")

            logger.warning(
                "Dispositivo registrado, pero no autorizado: id=%d lfdi=%s sfdi=%d estado=%s enabled=%s",
                registered_device.id,
                registered_device.lfdi,
                registered_device.sfdi,
                registered_device.authorization_status,
                registered_device.enabled,
            )
            raise PermissionError("El EndDevice esta registrado, pero su acceso esta bloqueado")

        DEVICE_REPOSITORY.update_last_seen(self.peer_device.id)
        logger.info(
            "EndDevice autorizado: id=%d sfdi=%d estado=%s",
            self.peer_device.id,
            self.peer_device.sfdi,
            self.peer_device.authorization_status,
        )

    def audit_event(self, event_category, event_type, severity="info", http_status=None, resource_type=None, subject=None, details=None):
        try:
            device = getattr(self, "peer_device", None)
            device_id = device.id if device is not None else None
            source_ip = self.client_address[0] if getattr(self, "client_address", None) else None
            path = urlparse(self.path).path if getattr(self, "path", None) else None

            return AUDIT_EVENT_REPOSITORY.save(
                device_id=device_id,
                event_category=event_category,
                event_type=event_type,
                severity=severity,
                http_method=getattr(self, "command", None),
                route=path,
                http_status=http_status,
                resource_type=resource_type,
                subject=subject,
                source_ip=source_ip,
                details=details,
            )
        except Exception:
            logger.exception("No fue posible guardar el evento de auditoria")
            return None

    def put_resource_type(self):
        try:
            route_config = PUT_ROUTES.get(urlparse(self.path).path)
            return route_config[0] if route_config is not None else None
        except Exception:
            logger.exception("No fue posible determinar el tipo de recurso PUT")
            return None

    def require_device_route_access(self, path):
        match = DEVICE_ROUTE_PATTERN.match(path)

        if match is None:
            return

        requested_device_id = int(match.group(1))

        if self.peer_device is None:
            raise PermissionError("No existe un dispositivo autenticado")

        if requested_device_id != self.peer_device.id:
            logger.warning(
                "Acceso denegado a recurso de otro dispositivo: authenticated_id=%d requested_id=%d route=%s",
                self.peer_device.id,
                requested_device_id,
                path,
            )
            raise PermissionError("El recurso solicitado pertenece a otro EndDevice")

    def require_xml_content_type(self):
        content_type = self.headers.get("Content-Type")

        if content_type is None:
            raise TypeError("La solicitud no contiene Content-Type")

        media_type = content_type.split(";", 1)[0].strip().lower()

        if media_type not in ACCEPTED_XML_TYPES:
            raise TypeError(f"Content-Type no soportado: {media_type}")

    def read_body(self):
        content_length = self.headers.get("Content-Length")

        if content_length is None:
            raise ValueError("La solicitud no contiene Content-Length")

        try:
            body_length = int(content_length)
        except ValueError as exc:
            raise ValueError("Content-Length invalido") from exc

        if body_length < 0:
            raise ValueError("Content-Length no puede ser negativo")

        if body_length > config.MAX_REQUEST_BODY:
            raise OverflowError("El cuerpo excede el tamano permitido")

        return self.rfile.read(body_length)

    def parse_xml_body(self, expected_roots=None):
        self.require_xml_content_type()
        body = self.read_body()

        if not body:
            raise ValueError("El cuerpo XML esta vacio")

        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise ValueError("El cuerpo contiene XML invalido") from exc

        namespace_prefix = f"{{{config.NAMESPACE}}}"

        if not root.tag.startswith(namespace_prefix):
            raise ValueError("El XML no utiliza el namespace IEEE 2030.5 esperado")

        local_name = root.tag.rsplit("}", 1)[-1]

        if expected_roots and local_name not in expected_roots:
            expected = ", ".join(sorted(expected_roots))
            raise ValueError(f"Elemento raiz no permitido: {local_name}; esperado: {expected}")

        return body, root, local_name

    def extract_timestamp(self, root, element_name):
        element = root.find(f"{{{config.NAMESPACE}}}{element_name}")

        if element is None or element.text is None:
            raise ValueError(f"El recurso no contiene {element_name}")

        try:
            timestamp = int(element.text)
        except ValueError as exc:
            raise ValueError(f"{element_name} debe ser un entero") from exc

        if timestamp < 0:
            raise ValueError(f"{element_name} no puede ser negativo")

        return timestamp

    def xml_text(self, root, element_name, required=False):
        element = root.find(f"{{{config.NAMESPACE}}}{element_name}")

        if element is None or element.text is None:
            if required:
                raise ValueError(f"El recurso no contiene {element_name}")
            return None

        value = element.text.strip()

        if required and not value:
            raise ValueError(f"El recurso contiene {element_name} vacio")

        return value or None

    def xml_integer(self, root, element_name, required=False):
        value = self.xml_text(root, element_name, required)

        if value is None:
            return None

        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{element_name} debe ser un entero") from exc

    def send_empty(self, status, allow=None, headers=None, close=False):
        self.send_response(status)

        if allow:
            self.send_header("Allow", allow)

        for name, value in (headers or {}).items():
            self.send_header(name, str(value))

        if close:
            self.send_header("Connection", "close")

        self.send_header("Content-Length", "0")
        self.end_headers()
        self.close_connection = close

    def send_xml(self, body, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/sep+xml")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        if self.command != "HEAD":
            self.wfile.write(body)
            self.wfile.flush()

        self.close_connection = False

    def process_read(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        self.require_device_route_access(path)
        logger.info("[%s] ruta=%s consulta=%s", self.command, path, query or {})
 
     
        default_control_match = DEFAULT_DER_CONTROL_ROUTE_PATTERN.match(path)

        if default_control_match is not None:
            device_id, fsa_id, program_id = map(
                int,
                default_control_match.groups(),
            )

            if device_id != self.peer_device.id:
                raise PermissionError(
                    "La ruta no pertenece al dispositivo autorizado"
                )

            body = xr.default_control_for_program(
                fsa_id,
                program_id,
            )

            if body is None:
                self.send_empty(404)
                return

            self.send_xml(body)
            return

        control_list_match = DER_CONTROL_LIST_ROUTE_PATTERN.match(path)

        if control_list_match is not None:
            device_id, fsa_id, program_id = map(
                int,
                control_list_match.groups(),
            )

            if device_id != self.peer_device.id:
                raise PermissionError(
                    "La ruta no pertenece al dispositivo autorizado"
                )

            body = xr.control_list_for_program(
                fsa_id,
                program_id,
            )

            if body is None:
                self.send_empty(404)
                return

            self.send_xml(body)
            return

        program_match = DER_PROGRAM_ROUTE_PATTERN.match(path)

        if program_match is not None:
            device_id, fsa_id, program_id = map(
                int,
                program_match.groups(),
            )

            if device_id != self.peer_device.id:
                raise PermissionError(
                    "La ruta no pertenece al dispositivo autorizado"
                )

            body = xr.program_by_route(
                fsa_id,
                program_id,
            )

            if body is None:
                self.send_empty(404)
                return

            self.send_xml(body)
            return

        program_list_match = DER_PROGRAM_LIST_ROUTE_PATTERN.match(path)

        if program_list_match is not None:
            device_id, fsa_id = map(
                int,
                program_list_match.groups(),
            )

            if device_id != self.peer_device.id:
                raise PermissionError(
                    "La ruta no pertenece al dispositivo autorizado"
                )

            body = xr.program_list_for_fsa(fsa_id)

            if body is None:
                self.send_empty(404)
                return

            self.send_xml(body)
            return

        fsa_match = FSA_ROUTE_PATTERN.match(path)

        if fsa_match is not None:
            device_id, fsa_id = map(
                int,
                fsa_match.groups(),
            )

            if device_id != self.peer_device.id:
                raise PermissionError(
                    "La ruta no pertenece al dispositivo autorizado"
                )

            body = xr.fsa_by_id(fsa_id)

            if body is None:
                self.send_empty(404)
                return

            self.send_xml(body)
            return

        control_match = DER_CONTROL_ROUTE_PATTERN.match(path)

        if control_match is not None:
            device_id, fsa_id, program_id, control_id = map(int, control_match.groups())

            if device_id != self.peer_device.id:
                raise PermissionError("La ruta DERControl no pertenece al dispositivo autorizado")

            body = xr.control_by_id(
                control_id,
                fsa_id,
                program_id,
            )

            if body is None:
                self.send_empty(404)
                return

            logger.info("[200] DERControl persistente id=%d ruta=%s bytes=%d", control_id, path, len(body))
            self.send_xml(body)
            return

        response_match = RESPONSE_ROUTE_PATTERN.match(path)

        if response_match is not None:
            response_set_id, response_id = map(int, response_match.groups())

            if response_set_id != 1:
                self.send_empty(404)
                return

            body = response_by_id(response_id)

            if body is None:
                self.send_empty(404)
                return

            logger.info("[200] Response persistente id=%d ruta=%s bytes=%d", response_id, path, len(body))
            self.send_xml(body)
            return

        mup_match = MIRROR_USAGE_POINT_ROUTE_PATTERN.match(path)

        if mup_match is not None:
            usage_point_id = int(mup_match.group(1))
            body = mirror_usage_point_by_id(usage_point_id)

            if body is None:
                self.send_empty(404)
                return

            logger.info("[200] MirrorUsagePoint id=%d ruta=%s bytes=%d", usage_point_id, path, len(body))
            self.send_xml(body)
            return

        reading_list_match = METER_READING_LIST_PATTERN.match(path)

        if reading_list_match is not None:
            usage_point_id, meter_id = map(int, reading_list_match.groups())

            try:
                limit = int(query.get("l", ["100"])[0])
            except ValueError:
                self.audit_event(
                    event_category="validation",
                    event_type="invalid_query_parameter",
                    severity="warning",
                    http_status=400,
                    resource_type="ReadingList",
                    details="El parametro l debe ser un entero positivo",
                )
                self.send_empty(400)
                return

            if limit <= 0:
                self.audit_event(
                    event_category="validation",
                    event_type="invalid_query_parameter",
                    severity="warning",
                    http_status=400,
                    resource_type="ReadingList",
                    details=f"Valor invalido para l: {limit}",
                )
                self.send_empty(400)
                return

            body = meter_reading_list(usage_point_id, meter_id, limit)

            if body is None:
                self.send_empty(404)
                return

            logger.info("[200] ReadingList mup_id=%d meter_id=%d ruta=%s limit=%d bytes=%d", usage_point_id, meter_id, path, limit, len(body))
            self.send_xml(body)
            return

        meter_match = MIRROR_METER_READING_ROUTE_PATTERN.match(path)

        if meter_match is not None:
            usage_point_id, meter_id = map(int, meter_match.groups())
            body = mirror_meter_reading_by_id(usage_point_id, meter_id)

            if body is None:
                self.send_empty(404)
                return

            logger.info("[200] MirrorMeterReading mup_id=%d meter_id=%d ruta=%s bytes=%d", usage_point_id, meter_id, path, len(body))
            self.send_xml(body)
            return

        meter_list_match = MIRROR_METER_READING_LIST_PATTERN.match(path)

        if meter_list_match is not None:
            usage_point_id = int(meter_list_match.group(1))
            body = mirror_meter_reading_list(usage_point_id)

            if body is None:
                self.send_empty(404)
                return

            logger.info("[200] MirrorMeterReadingList mup_id=%d ruta=%s bytes=%d", usage_point_id, path, len(body))
            self.send_xml(body)
            return

        generator = RESOURCES.get(path)

        if generator is None:
            self.send_empty(404)
            return 

        try:
            body = generator()

            if body is None:
                logger.info("[404] Recurso temporal expirado: %s", path)
                self.send_empty(404)
                return

            logger.info("[200] %s, %d bytes", path, len(body))
            self.send_xml(body)
        except Exception:
            logger.exception("[500] Error generando %s", path)
            self.send_empty(500)

    def process_write(self):
        path = urlparse(self.path).path
        mup_match = MIRROR_USAGE_POINT_ROUTE_PATTERN.match(path)

        if mup_match is not None:
            self.process_mirror_usage_point(int(mup_match.group(1)))
            return

        handler_name = POST_ROUTES.get(path)

        if handler_name is None:
            self.send_empty(404, close=True)
            return

        getattr(self, handler_name)()

    def process_put(self):
        path = urlparse(self.path).path
        self.require_device_route_access(path)
        route_config = PUT_ROUTES.get(path)

        if route_config is None:
            self.audit_event(
                event_category="http",
                event_type="method_not_allowed",
                severity="warning",
                http_status=405,
                details="La ruta no admite PUT",
            )
            self.send_empty(405, allow="GET, HEAD", close=True)
            return

        resource_type, expected_roots, timestamp_name = route_config
        body, root, local_name = self.parse_xml_body(expected_roots)
        SEP_XML_VALIDATOR.validate(body)
        source_timestamp = self.extract_timestamp(root, timestamp_name) if timestamp_name else None

        record = DER_RESOURCE_REPOSITORY.save(
            device_id=self.peer_device.id,
            resource_type=resource_type,
            xml_body=body,
            source_timestamp=source_timestamp,
        )

        logger.info(
            "Recurso DER actualizado: device_id=%d tipo=%s source_timestamp=%s bytes=%d record_id=%d",
            self.peer_device.id,
            local_name,
            source_timestamp,
            len(body),
            record.id,
        )

        self.audit_event(
            event_category="resource",
            event_type="resource_updated",
            severity="info",
            http_status=200,
            resource_type=resource_type,
            details=f"Recurso {resource_type} actualizado",
        )

        self.send_empty(200)

    def process_response(self):
        body, root, response_type = self.parse_xml_body(
            {
                "Response",
                "DERControlResponse",
                "DefaultDERControlResponse",
            }
        )

        SEP_XML_VALIDATOR.validate(body)

        subject = self.xml_text(root, "subject")
        subject = subject.upper() if subject else None 
        response_status = self.xml_integer(root, "status")
        created_datetime = self.xml_integer(root, "createdDateTime")

        response = CONTROL_RESPONSE_REPOSITORY.save(
            device_id=self.peer_device.id,
            response_type=response_type,
            subject=subject,
            response_status=response_status,
            created_datetime=created_datetime,
            xml_body=body,
        )

        previous_control = None
        updated_control = None
        response_status_name = None

        if response_type == "DERControlResponse" and subject and response_status is not None:
            previous_control, updated_control, response_status_name = DER_CONTROL_REPOSITORY.apply_response_status(
                subject,
                response_status,
                updated_at=created_datetime,
            )

            if previous_control is None:
                logger.warning(
                    "DERControlResponse sin control relacionado: subject=%s status=%s",
                    subject,
                    response_status,
                )
            else:
                logger.info(
                    "DERControl correlacionado: mrid=%s response_status=%s response_name=%s previous_status=%s current_status=%s",
                    subject,
                    response_status,
                    response_status_name,
                    previous_control.control_status,
                    updated_control.control_status,
                )

        STORE.add_response(body)

        logger.info(
            "Respuesta IEEE 2030.5 almacenada: device_id=%d tipo=%s subject=%s status=%s bytes=%d response_id=%d",
            self.peer_device.id,
            response_type,
            subject,
            response_status,
            len(body),
            response.id,
        )


        control_details = ""

        if previous_control is not None:
            control_details = (
                f" previous_status={previous_control.control_status}"
                f" current_status={updated_control.control_status}"
            )

        self.audit_event(
            event_category="response",
            event_type="control_response_received",
            severity="info",
            http_status=201,
            resource_type=response_type,
            subject=subject,
            details=(
                f"Respuesta {response_type} persistida"
                f" response_status={response_status}"
                f" response_name={response_status_name}"
                f"{control_details}"
            ),
        )


        self.send_empty(
            201,
            headers={"Location": f"/rsps/1/rsp/{response.id}"},
        )

    def xml_hex_integer(self, root, element_name, required=False):
        value = self.xml_text(root, element_name, required)

        if value is None:
            return None

        try:
            return int(value, 16)
        except ValueError as exc:
            raise ValueError(f"{element_name} debe ser hexadecimal") from exc

    def child_text(self, root, element_name, required=False):
        return self.xml_text(root, element_name, required)

    def parse_reading_type(self, meter_root):
        reading_type_root = meter_root.find(f"{{{config.NAMESPACE}}}ReadingType")

        if reading_type_root is None:
            return None

        def optional_integer(name):
            node = reading_type_root.find(f"{{{config.NAMESPACE}}}{name}")
            return int(node.text.strip()) if node is not None and node.text else None

        uom = optional_integer("uom")

        if uom is None:
            raise ValueError("ReadingType no contiene uom")

        description = self.child_text(meter_root, "description")
        reading_type = reading_type_for_uom(uom, description)
        phase_code = optional_integer("phase")

        if phase_code is None:
            phase_code = default_phase_for_type(reading_type)

        phase_names = {0: None, 32: "C", 33: "CN", 40: "CA", 64: "B", 65: "BN", 66: "BC", 128: "A", 129: "AN", 132: "AB", 224: "ABC"}

        return {
            "reading_type": reading_type,
            "phase": phase_names.get(phase_code, str(phase_code)),
            "uom": uom,
            "power_of_ten_multiplier": optional_integer("powerOfTenMultiplier") or 0,
            "flow_direction": optional_integer("flowDirection"),
            "accumulation_behaviour": optional_integer("accumulationBehaviour"),
            "commodity": optional_integer("commodity"),
            "data_qualifier": optional_integer("dataQualifier"),
            "kind": optional_integer("kind"),
            "reading_type_xml": ET.tostring(reading_type_root, encoding="utf-8"),
        }

    def save_meter_reading_definition(self, usage_point, meter_root):
        mrid = self.child_text(meter_root, "mRID", required=True).upper()
        definition = self.parse_reading_type(meter_root)
        existing = MIRROR_METER_READING_REPOSITORY.get_by_usage_point_and_mrid(usage_point.id, mrid)

        if definition is None:
            if existing is None:
                raise ValueError(f"MirrorMeterReading {mrid} no contiene ReadingType")
            meter = existing
        else:
            meter = MIRROR_METER_READING_REPOSITORY.save(
                usage_point_id=usage_point.id,
                mrid=mrid,
                description=self.child_text(meter_root, "description"),
                **definition,
            )

        reading_root = meter_root.find(f"{{{config.NAMESPACE}}}Reading")

        if reading_root is not None:
            self.save_meter_reading_value(meter, reading_root)

        return meter

    def save_meter_reading_value(self, meter, reading_root):
        value_node = reading_root.find(f"{{{config.NAMESPACE}}}value")

        if value_node is None or value_node.text is None:
            return None

        period = reading_root.find(f"{{{config.NAMESPACE}}}timePeriod")
        start = period.find(f"{{{config.NAMESPACE}}}start") if period is not None else None

        if start is None or start.text is None:
            raise ValueError("Reading no contiene timePeriod/start")

        quality_node = reading_root.find(f"{{{config.NAMESPACE}}}qualityFlags")
        quality_flags = int(quality_node.text.strip(), 16) if quality_node is not None and quality_node.text else None

        return METER_READING_REPOSITORY.save(
            meter_reading_id=meter.id,
            value=int(value_node.text.strip()),
            reading_time=int(start.text.strip()),
            quality_flags=quality_flags,
            xml_body=ET.tostring(reading_root, encoding="utf-8"),
        )


    def process_mirror_usage_point(self, usage_point_id=None):
        expected_roots = {"MirrorUsagePoint"} if usage_point_id is None else {"MirrorMeterReading", "MirrorMeterReadingList"}
        body, root, local_name = self.parse_xml_body(expected_roots)
        SEP_XML_VALIDATOR.validate(body)

        if usage_point_id is None:
            mrid = self.xml_text(root, "mRID", required=True).upper()
            device_lfdi = self.xml_text(root, "deviceLFDI", required=True).lower()

            if device_lfdi != self.peer_identity["lfdi_hex"].lower():
                raise PermissionError("deviceLFDI no corresponde al certificado autenticado")

            role_flags = self.xml_hex_integer(root, "roleFlags", required=True)
            service_category = self.xml_integer(root, "serviceCategoryKind", required=True)
            status = self.xml_integer(root, "status", required=True)
            post_rate = self.xml_integer(root, "postRate") or 300

            usage_point = MIRROR_USAGE_POINT_REPOSITORY.save(
                device_id=self.peer_device.id,
                mrid=mrid,
                description=self.xml_text(root, "description"),
                role_flags=role_flags,
                service_category=service_category,
                post_rate=post_rate,
                device_lfdi=device_lfdi,
                status=status,
                xml_body=body,
            )

            meters = root.findall(f"{{{config.NAMESPACE}}}MirrorMeterReading")

            for meter_root in meters:
                self.save_meter_reading_definition(usage_point, meter_root)

            self.audit_event(
                event_category="metering",
                event_type="mirror_usage_point_saved",
                severity="info",
                http_status=201,
                resource_type="MirrorUsagePoint",
                subject=mrid,
                details=f"MirrorUsagePoint persistido con {len(meters)} definiciones",
            )

            logger.info(
                "MirrorUsagePoint persistido: device_id=%d mup_id=%d mrid=%s meters=%d post_rate=%d",
                self.peer_device.id,
                usage_point.id,
                usage_point.mrid,
                len(meters),
                usage_point.post_rate,
            )

            self.send_empty(201, headers={"Location": f"/mup/{usage_point.id}"})
            return

        usage_point = MIRROR_USAGE_POINT_REPOSITORY.get_by_id(usage_point_id)

        if usage_point is None:
            self.send_empty(404, close=True)
            return

        if usage_point.device_id != self.peer_device.id:
            raise PermissionError("MirrorUsagePoint pertenece a otro EndDevice")

        meter_roots = [root] if local_name == "MirrorMeterReading" else root.findall(f"{{{config.NAMESPACE}}}MirrorMeterReading")

        if not meter_roots:
            raise ValueError("La solicitud no contiene MirrorMeterReading")

        saved = []

        for meter_root in meter_roots:
            saved.append(self.save_meter_reading_definition(usage_point, meter_root))

        self.audit_event(
            event_category="metering",
            event_type="mirror_meter_reading_saved",
            severity="info",
            http_status=201,
            resource_type=local_name,
            subject=usage_point.mrid,
            details=f"Telemetria persistida: {len(saved)} MirrorMeterReading",
        )

        logger.info(
            "Telemetria persistida: device_id=%d mup_id=%d elemento=%s meters=%d bytes=%d",
            self.peer_device.id,
            usage_point.id,
            local_name,
            len(saved),
            len(body),
        )

        self.send_empty(201, headers={"Location": f"/mup/{usage_point.id}"})
    
    def do_GET(self):
        try:
            self.authenticate_client()
            self.process_read()
        except PermissionError as exc:
            logger.warning("Cliente no autorizado: %s", exc)
            self.send_empty(403)
        except Exception:
            logger.exception("Error general procesando GET")
            self.send_empty(500)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        try:
            self.authenticate_client()
            self.process_write()
        except OverflowError as exc:
            logger.warning("Cuerpo POST demasiado grande: %s", exc)
            self.audit_event(
                event_category="http",
                event_type="request_too_large",
                severity="warning",
                http_status=413,
                details=str(exc),
            )
            self.send_empty(413, close=True)
        except TypeError as exc:
            logger.warning("Content-Type POST no soportado: %s", exc)
            self.audit_event(
                event_category="http",
                event_type="unsupported_media_type",
                severity="warning",
                http_status=415,
                details=str(exc),
            )
            self.send_empty(415, close=True)
        except ValueError as exc:
            logger.warning("Solicitud POST invalida: %s", exc)
            event_type = "xsd_validation_failed" if "sep.xsd" in str(exc) else "invalid_request"
            self.audit_event(
                event_category="validation",
                event_type=event_type,
                severity="warning",
                http_status=400,
                details=str(exc),
            )
            self.send_empty(400, close=True)
        except PermissionError as exc:
            logger.warning("Cliente no autorizado para POST: %s", exc)
            self.audit_event(
                event_category="authorization",
                event_type="acl_access_failed",
                severity="warning",
                http_status=403,
                details=str(exc),
            )
            self.send_empty(403, close=True)
        except Exception as exc:
            logger.exception("Error general procesando POST")
            self.audit_event(
                event_category="system",
                event_type="internal_error",
                severity="error",
                http_status=500,
                details=str(exc),
            )
            self.send_empty(500, close=True)

    def do_PUT(self):
        try:
            self.authenticate_client()
            self.process_put()
        except OverflowError as exc:
            logger.warning("Cuerpo PUT demasiado grande: %s", exc)
            self.audit_event(
                event_category="http",
                event_type="request_too_large",
                severity="warning",
                http_status=413,
                resource_type=self.put_resource_type(),
                details=str(exc),
            )
            self.send_empty(413, close=True)
        except TypeError as exc:
            logger.warning("Content-Type PUT no soportado: %s", exc)
            self.audit_event(
                event_category="http",
                event_type="unsupported_media_type",
                severity="warning",
                http_status=415,
                resource_type=self.put_resource_type(),
                details=str(exc),
            )
            self.send_empty(415, close=True)
        except ValueError as exc:
            logger.warning("Solicitud PUT invalida: %s", exc)
            event_type = "xsd_validation_failed" if "sep.xsd" in str(exc) else "invalid_request"
            self.audit_event(
                event_category="validation",
                event_type=event_type,
                severity="warning",
                http_status=400,
                resource_type=self.put_resource_type(),
                details=str(exc),
            )
            self.send_empty(400, close=True)
        except PermissionError as exc:
            logger.warning("Cliente no autorizado para PUT: %s", exc)
            self.audit_event(
                event_category="authorization",
                event_type="acl_access_failed",
                severity="warning",
                http_status=403,
                resource_type=self.put_resource_type(),
                details=str(exc),
            )
            self.send_empty(403, close=True)
        except Exception as exc:
            logger.exception("Error general procesando PUT")
            self.audit_event(
                event_category="system",
                event_type="internal_error",
                severity="error",
                http_status=500,
                resource_type=self.put_resource_type(),
                details=str(exc),
            )
            self.send_empty(500, close=True)

    def method_not_allowed(self):
        self.send_empty(405, allow="GET, HEAD, POST, PUT")

    do_DELETE = method_not_allowed
    do_PATCH = method_not_allowed


class MockHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address, handler_class, ssl_context=None):
        super().__init__(server_address, handler_class)
        self.ssl_context = ssl_context

    def get_request(self):
        raw_socket, client_address = self.socket.accept()

        if self.ssl_context is None:
            return raw_socket, client_address

        try:
            tls_socket = self.ssl_context.wrap_socket(raw_socket, server_side=True)
        except (ssl.SSLError, OSError):
            raw_socket.close()
            logger.exception(
                "Handshake TLS rechazado para %s:%s",
                client_address[0],
                client_address[1],
            )
            raise

        return tls_socket, client_address
