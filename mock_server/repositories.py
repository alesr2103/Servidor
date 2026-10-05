"""Repositorios persistentes de dispositivos y registros."""

import time

from . import config
from .database import connect
from .identity import identity_from_certificate_file, load_certificate_der
from .models import (
    AuditEventRecord,
    ControlResponseRecord,
    DefaultDERControlRecord,
    DERControlRecord,
    DERProgramRecord,
    DERResourceRecord,
    DeviceRecord,
    MeterReadingRecord,
    MirrorMeterReadingRecord,
    MirrorUsagePointRecord,
)

def _device_from_row(row):
    if row is None:
        return None

    return DeviceRecord(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        role=row["role"],
        lfdi=row["lfdi"],
        sfdi=row["sfdi"],
        fingerprint_sha256=row["fingerprint_sha256"],
        authorization_status=row["authorization_status"],
        enabled=bool(row["enabled"]),
        registered_at=row["registered_at"],
        last_seen=row["last_seen"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class DeviceRepository:
    def find_by_id(self, device_id):
        with connect() as connection:
            row = connection.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()

        return _device_from_row(row)

    def find_by_lfdi(self, lfdi):
        with connect() as connection:
            row = connection.execute("SELECT * FROM devices WHERE lower(lfdi) = lower(?)", (lfdi,)).fetchone()

        return _device_from_row(row)

    def find_by_sfdi(self, sfdi):
        with connect() as connection:
            row = connection.execute("SELECT * FROM devices WHERE sfdi = ?", (sfdi,)).fetchone()

        return _device_from_row(row)

    def find_by_fingerprint(self, fingerprint_sha256):
        with connect() as connection:
            row = connection.execute("SELECT * FROM devices WHERE lower(fingerprint_sha256) = lower(?)", (fingerprint_sha256,)).fetchone()

        return _device_from_row(row)

    def find_authorized_by_lfdi(self, lfdi):
        device = self.find_by_lfdi(lfdi)

        if device is None or not device.is_authorized:
            return None

        return device

    def list_devices(self):
        with connect() as connection:
            rows = connection.execute("SELECT * FROM devices ORDER BY id").fetchall()

        return [_device_from_row(row) for row in rows]

    def update_last_seen(self, device_id, timestamp=None):
        now = int(time.time()) if timestamp is None else int(timestamp)

        with connect() as connection:
            connection.execute("UPDATE devices SET last_seen = ?, updated_at = ? WHERE id = ?", (now, now, device_id))

    def set_authorization_status(self, device_id, status):
        allowed = {"pending", "active", "blocked", "retired"}

        if status not in allowed:
            raise ValueError(f"Estado de autorización inválido: {status}")

        now = int(time.time())

        with connect() as connection:
            cursor = connection.execute("UPDATE devices SET authorization_status = ?, updated_at = ? WHERE id = ?", (status, now, device_id))

        if cursor.rowcount == 0:
            raise LookupError(f"Dispositivo inexistente: {device_id}")

    def register_certificate(self, certificate_path, name, description="", role="device", pin=None, poll_rate=None):
        identity = identity_from_certificate_file(certificate_path)
        certificate_der = load_certificate_der(certificate_path)
        now = int(time.time())
        pin = config.REGISTRATION_PIN if pin is None else int(pin)
        poll_rate = config.REGISTRATION_POLL_RATE if poll_rate is None else int(poll_rate)

        existing_lfdi = self.find_by_lfdi(identity.lfdi_hex)
        existing_fingerprint = self.find_by_fingerprint(identity.fingerprint_sha256)

        if existing_lfdi is not None and existing_fingerprint is not None:
            if existing_lfdi.id != existing_fingerprint.id:
                raise ValueError("El LFDI y el fingerprint pertenecen a dispositivos diferentes")

            return existing_lfdi

        if existing_lfdi is not None:
            raise ValueError(f"El LFDI ya pertenece al dispositivo {existing_lfdi.id}")

        if existing_fingerprint is not None:
            raise ValueError(f"El fingerprint ya pertenece al dispositivo {existing_fingerprint.id}")

        with connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO devices (
                    name,
                    description,
                    role,
                    lfdi,
                    sfdi,
                    fingerprint_sha256,
                    authorization_status,
                    enabled,
                    registered_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    name,
                    description,
                    role,
                    identity.lfdi_hex,
                    identity.sfdi,
                    identity.fingerprint_sha256,
                    config.DEFAULT_AUTHORIZATION_STATUS,
                    now,
                    now,
                    now,
                ),
            )

            device_id = cursor.lastrowid

            connection.execute(
                """
                INSERT INTO device_certificates (
                    device_id,
                    fingerprint_sha256,
                    certificate_der,
                    active,
                    created_at
                )
                VALUES (?, ?, ?, 1, ?)
                """,
                (device_id, identity.fingerprint_sha256, certificate_der, now),
            )

            connection.execute(
                """
                INSERT INTO registrations (
                    device_id,
                    pin,
                    registered_at,
                    poll_rate,
                    active
                )
                VALUES (?, ?, ?, ?, 1)
                """,
                (device_id, pin, now, poll_rate),
            )

        return self.find_by_id(device_id)


DER_RESOURCE_TYPES = {
    "DERCapability",
    "DERSettings",
    "DERStatus",
    "DERAvailability",
}


def _der_resource_from_row(row):
    if row is None:
        return None

    return DERResourceRecord(
        id=row["id"],
        device_id=row["device_id"],
        resource_type=row["resource_type"],
        xml_body=bytes(row["xml_body"]),
        source_timestamp=row["source_timestamp"],
        received_at=row["received_at"],
        updated_at=row["updated_at"],
    )


class DERResourceRepository:
    def get(self, device_id, resource_type):
        self._validate_type(resource_type)

        with connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM der_resources
                WHERE device_id = ? AND resource_type = ?
                """,
                (device_id, resource_type),
            ).fetchone()

        return _der_resource_from_row(row)

    def save(
        self,
        device_id,
        resource_type,
        xml_body,
        source_timestamp=None,
        received_at=None,
    ):
        self._validate_type(resource_type)

        if not isinstance(xml_body, bytes) or not xml_body:
            raise ValueError(
                "xml_body debe contener bytes XML"
            )

        now = (
            int(time.time())
            if received_at is None
            else int(received_at)
        )

        with connect() as connection:
            connection.execute(
                """
                INSERT INTO der_resources (
                    device_id,
                    resource_type,
                    xml_body,
                    source_timestamp,
                    received_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, resource_type)
                DO UPDATE SET
                    xml_body = excluded.xml_body,
                    source_timestamp = excluded.source_timestamp,
                    received_at = excluded.received_at,
                    updated_at = excluded.updated_at
                """,
                (
                    device_id,
                    resource_type,
                    xml_body,
                    source_timestamp,
                    now,
                    now,
                ),
            )

        return self.get(
            device_id,
            resource_type,
        )

    def list_for_device(self, device_id):
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM der_resources
                WHERE device_id = ?
                ORDER BY resource_type
                """,
                (device_id,),
            ).fetchall()

        return [
            _der_resource_from_row(row)
            for row in rows
        ]

    def delete(self, device_id, resource_type):
        self._validate_type(resource_type)

        with connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM der_resources
                WHERE device_id = ?
                  AND resource_type = ?
                """,
                (device_id, resource_type),
            )

        return cursor.rowcount > 0

    @staticmethod
    def _validate_type(resource_type):
        if resource_type not in DER_RESOURCE_TYPES:
            raise ValueError(
                "Tipo de recurso DER inválido: "
                f"{resource_type}"
            )


DER_RESOURCE_REPOSITORY = DERResourceRepository()

AUDIT_SEVERITIES = {"info", "warning", "error", "critical"}


def _audit_event_from_row(row):
    if row is None:
        return None

    return AuditEventRecord(
        id=row["id"],
        device_id=row["device_id"],
        event_category=row["event_category"],
        event_type=row["event_type"],
        severity=row["severity"],
        http_method=row["http_method"],
        route=row["route"],
        http_status=row["http_status"],
        resource_type=row["resource_type"],
        subject=row["subject"],
        source_ip=row["source_ip"],
        details=row["details"],
        created_at=row["created_at"],
    )


AUDIT_SEVERITIES = {"info", "warning", "error", "critical"}


def _audit_event_from_row(row):
    if row is None:
        return None

    return AuditEventRecord(
        id=row["id"],
        device_id=row["device_id"],
        event_category=row["event_category"],
        event_type=row["event_type"],
        severity=row["severity"],
        http_method=row["http_method"],
        route=row["route"],
        http_status=row["http_status"],
        resource_type=row["resource_type"],
        subject=row["subject"],
        source_ip=row["source_ip"],
        details=row["details"],
        created_at=row["created_at"],
    )


class AuditEventRepository:
    def save(
        self,
        event_category,
        event_type,
        severity="info",
        device_id=None,
        http_method=None,
        route=None,
        http_status=None,
        resource_type=None,
        subject=None,
        source_ip=None,
        details=None,
        created_at=None,
    ):
        if not event_category or not event_category.strip():
            raise ValueError("event_category es obligatorio")

        if not event_type or not event_type.strip():
            raise ValueError("event_type es obligatorio")

        if severity not in AUDIT_SEVERITIES:
            raise ValueError(f"Severidad invalida: {severity}")

        if http_status is not None:
            http_status = int(http_status)

            if not 100 <= http_status <= 599:
                raise ValueError(f"Estado HTTP invalido: {http_status}")

        timestamp = int(time.time()) if created_at is None else int(created_at)

        with connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO audit_events (
                    device_id,
                    event_category,
                    event_type,
                    severity,
                    http_method,
                    route,
                    http_status,
                    resource_type,
                    subject,
                    source_ip,
                    details,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    event_category.strip(),
                    event_type.strip(),
                    severity,
                    http_method,
                    route,
                    http_status,
                    resource_type,
                    subject,
                    source_ip,
                    details,
                    timestamp,
                ),
            )
            event_id = cursor.lastrowid

        return self.get_by_id(event_id)

    def get_by_id(self, event_id):
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM audit_events WHERE id = ?",
                (event_id,),
            ).fetchone()

        return _audit_event_from_row(row)

    def list_recent(self, limit=100):
        limit = self._validate_limit(limit)

        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM audit_events
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [_audit_event_from_row(row) for row in rows]

    def list_for_device(self, device_id, limit=100):
        limit = self._validate_limit(limit)

        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM audit_events
                WHERE device_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()

        return [_audit_event_from_row(row) for row in rows]

    def list_errors(self, limit=100):
        limit = self._validate_limit(limit)

        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM audit_events
                WHERE severity IN ('error', 'critical')
                   OR http_status >= 400
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [_audit_event_from_row(row) for row in rows]

    def count(self):
        with connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM audit_events"
            ).fetchone()

        return row["total"]

    def delete_older_than(self, timestamp):
        with connect() as connection:
            cursor = connection.execute(
                "DELETE FROM audit_events WHERE created_at < ?",
                (int(timestamp),),
            )

        return cursor.rowcount

    @staticmethod
    def _validate_limit(limit):
        limit = int(limit)

        if limit <= 0:
            raise ValueError("limit debe ser mayor que cero")

        return limit


AUDIT_EVENT_REPOSITORY = AuditEventRepository()

CONTROL_RESPONSE_TYPES = {
    "Response",
    "DERControlResponse",
    "DefaultDERControlResponse",
}


def _control_response_from_row(row):
    if row is None:
        return None

    return ControlResponseRecord(
        id=row["id"],
        device_id=row["device_id"],
        response_type=row["response_type"],
        subject=row["subject"],
        response_status=row["response_status"],
        created_datetime=row["created_datetime"],
        xml_body=bytes(row["xml_body"]),
        received_at=row["received_at"],
    )


class ControlResponseRepository:
    def save(
        self,
        device_id,
        response_type,
        xml_body,
        subject=None,
        response_status=None,
        created_datetime=None,
        received_at=None,
    ):
        self._validate_type(response_type)

        if not isinstance(xml_body, bytes) or not xml_body:
            raise ValueError("xml_body debe contener bytes XML")

        if response_status is not None:
            response_status = int(response_status)

            if not 0 <= response_status <= 255:
                raise ValueError(
                    f"Estado de respuesta invalido: {response_status}"
                )

        timestamp = (
            int(time.time())
            if received_at is None
            else int(received_at)
        )

        with connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO control_responses (
                    device_id,
                    response_type,
                    subject,
                    response_status,
                    created_datetime,
                    xml_body,
                    received_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    device_id,
                    response_type,
                    subject,
                    response_status,
                    created_datetime,
                    xml_body,
                    timestamp,
                ),
            )
            response_id = cursor.lastrowid

        return self.get_by_id(response_id)

    def get_by_id(self, response_id):
        with connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM control_responses
                WHERE id = ?
                """,
                (response_id,),
            ).fetchone()

        return _control_response_from_row(row)

    def list_for_device(self, device_id, limit=100):
        limit = self._validate_limit(limit)

        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM control_responses
                WHERE device_id = ?
                ORDER BY received_at DESC, id DESC
                LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()

        return [
            _control_response_from_row(row)
            for row in rows
        ]


    def list_for_subject(self, subject, limit=100):
        limit = self._validate_limit(limit)

        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM control_responses
                WHERE subject = ? COLLATE NOCASE
                ORDER BY received_at DESC, id DESC
                LIMIT ?
                """,
                (subject, limit),
            ).fetchall()

        return [_control_response_from_row(row) for row in rows]

    def count(self):
        with connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM control_responses
                """
            ).fetchone()

        return row["total"]

    def delete_older_than(self, timestamp):
        with connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM control_responses
                WHERE received_at < ?
                """,
                (int(timestamp),),
            )

        return cursor.rowcount

    @staticmethod
    def _validate_type(response_type):
        if response_type not in CONTROL_RESPONSE_TYPES:
            raise ValueError(
                f"Tipo de respuesta invalido: {response_type}"
            )

    @staticmethod
    def _validate_limit(limit):
        limit = int(limit)

        if limit <= 0:
            raise ValueError(
                "limit debe ser mayor que cero"
            )

        return limit


CONTROL_RESPONSE_REPOSITORY = ControlResponseRepository()

DER_CONTROL_STATUSES = {
    "scheduled",
    "active",
    "received",
    "started",
    "completed",
    "rejected",
    "cancelled",
    "expired",
    "superseded",
}


def _der_program_from_row(row):
    if row is None:
        return None

    return DERProgramRecord(
        id=row["id"],
        device_id=row["device_id"],
        mrid=row["mrid"],
        description=row["description"],
        version=row["version"],
        primacy=row["primacy"],
        active=bool(row["active"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _default_der_control_from_row(row):
    if row is None:
        return None

    return DefaultDERControlRecord(
        id=row["id"],
        program_id=row["program_id"],
        mrid=row["mrid"],
        description=row["description"],
        version=row["version"],
        control_xml=bytes(row["control_xml"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _der_control_from_row(row):
    if row is None:
        return None

    return DERControlRecord(
        id=row["id"],
        program_id=row["program_id"],
        device_id=row["device_id"],
        mrid=row["mrid"],
        description=row["description"],
        version=row["version"],
        creation_time=row["creation_time"],
        start_time=row["start_time"],
        duration=row["duration"],
        control_status=row["control_status"],
        control_xml=bytes(row["control_xml"]),
        cancelled_at=row["cancelled_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )

class DERProgramRepository:
    def save(
        self,
        device_id,
        mrid,
        description,
        version=1,
        primacy=0,
        active=True,
        created_at=None,
    ):
        if not mrid or not mrid.strip():
            raise ValueError("mrid es obligatorio")

        if not description or not description.strip():
            raise ValueError("description es obligatorio")

        version = int(version)
        primacy = int(primacy)

        if version < 0:
            raise ValueError("version no puede ser negativa")

        if not 0 <= primacy <= 255:
            raise ValueError("primacy debe estar entre 0 y 255")

        timestamp = int(time.time()) if created_at is None else int(created_at)

        with connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO der_programs (
                    device_id,
                    mrid,
                    description,
                    version,
                    primacy,
                    active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(device_id),
                    mrid.strip(),
                    description.strip(),
                    version,
                    primacy,
                    int(bool(active)),
                    timestamp,
                    timestamp,
                ),
            )
            program_id = cursor.lastrowid

        return self.get_by_id(program_id)

    def get_by_id(self, program_id):
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM der_programs WHERE id = ?",
                (int(program_id),),
            ).fetchone()

        return _der_program_from_row(row)

    def get_by_mrid(self, mrid):
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM der_programs WHERE mrid = ?",
                (mrid,),
            ).fetchone()

        return _der_program_from_row(row)

    def get_active_for_device(self, device_id):
        with connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM der_programs
                WHERE device_id = ? AND active = 1
                ORDER BY primacy ASC, id ASC
                LIMIT 1
                """,
                (int(device_id),),
            ).fetchone()

        return _der_program_from_row(row)

    def list_for_device(self, device_id, active_only=False):
        query = "SELECT * FROM der_programs WHERE device_id = ?"
        parameters = [int(device_id)]

        if active_only:
            query += " AND active = 1"

        query += " ORDER BY primacy ASC, id ASC"

        with connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [_der_program_from_row(row) for row in rows]

    def set_active(self, program_id, active):
        timestamp = int(time.time())

        with connect() as connection:
            cursor = connection.execute(
                """
                UPDATE der_programs
                SET active = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(bool(active)), timestamp, int(program_id)),
            )

        if cursor.rowcount == 0:
            return None

        return self.get_by_id(program_id)

class DefaultDERControlRepository:
    def save(
        self,
        program_id,
        mrid,
        description,
        control_xml,
        version=1,
        created_at=None,
    ):
        if not mrid or not mrid.strip():
            raise ValueError("mrid es obligatorio")

        if not description or not description.strip():
            raise ValueError("description es obligatorio")

        if not isinstance(control_xml, bytes) or not control_xml:
            raise ValueError("control_xml debe contener bytes XML")

        version = int(version)

        if version < 0:
            raise ValueError("version no puede ser negativa")

        timestamp = int(time.time()) if created_at is None else int(created_at)

        with connect() as connection:
            connection.execute(
                """
                INSERT INTO default_der_controls (
                    program_id,
                    mrid,
                    description,
                    version,
                    control_xml,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(program_id)
                DO UPDATE SET
                    mrid = excluded.mrid,
                    description = excluded.description,
                    version = excluded.version,
                    control_xml = excluded.control_xml,
                    updated_at = excluded.updated_at
                """,
                (
                    int(program_id),
                    mrid.strip(),
                    description.strip(),
                    version,
                    control_xml,
                    timestamp,
                    timestamp,
                ),
            )

        return self.get_for_program(program_id)

    def get_by_id(self, control_id):
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM default_der_controls WHERE id = ?",
                (int(control_id),),
            ).fetchone()

        return _default_der_control_from_row(row)

    def get_for_program(self, program_id):
        with connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM default_der_controls
                WHERE program_id = ?
                """,
                (int(program_id),),
            ).fetchone()

        return _default_der_control_from_row(row)

class DERControlRepository:
    def save(
        self,
        program_id,
        device_id,
        mrid,
        description,
        creation_time,
        start_time,
        duration,
        control_xml,
        version=1,
        control_status="scheduled",
        created_at=None,
    ):
        if not mrid or not mrid.strip():
            raise ValueError("mrid es obligatorio")

        if not description or not description.strip():
            raise ValueError("description es obligatorio")

        if not isinstance(control_xml, bytes) or not control_xml:
            raise ValueError("control_xml debe contener bytes XML")

        version = int(version)
        duration = int(duration)
        creation_time = int(creation_time)
        start_time = int(start_time)

        if version < 0:
            raise ValueError("version no puede ser negativa")

        if duration <= 0:
            raise ValueError("duration debe ser mayor que cero")

        self._validate_status(control_status)
        timestamp = int(time.time()) if created_at is None else int(created_at)

        with connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO der_controls (
                    program_id,
                    device_id,
                    mrid,
                    description,
                    version,
                    creation_time,
                    start_time,
                    duration,
                    control_status,
                    control_xml,
                    cancelled_at,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    int(program_id),
                    int(device_id),
                    mrid.strip().upper(),
                    description.strip(),
                    version,
                    creation_time,
                    start_time,
                    duration,
                    control_status,
                    control_xml,
                    timestamp,
                    timestamp,
                ),
            )
            control_id = cursor.lastrowid

        return self.get_by_id(control_id)

    def get_by_id(self, control_id):
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM der_controls WHERE id = ?",
                (int(control_id),),
            ).fetchone()

        return _der_control_from_row(row)

    def get_by_mrid(self, mrid):
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM der_controls WHERE mrid = ? COLLATE NOCASE",
                (mrid,),
            ).fetchone()

        return _der_control_from_row(row)


    def list_for_device(self, device_id, include_terminal=True):
        query = "SELECT * FROM der_controls WHERE device_id = ?"
        parameters = [int(device_id)]

        if not include_terminal:
            query += (
                " AND control_status NOT IN "
                "('completed', 'rejected', 'cancelled', 'expired')"
            )

        query += " ORDER BY start_time ASC, id ASC"

        with connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [_der_control_from_row(row) for row in rows]

    def list_for_program(self, program_id, include_terminal=True):
        query = "SELECT * FROM der_controls WHERE program_id = ?"
        parameters = [int(program_id)]

        if not include_terminal:
            query += (
                " AND control_status NOT IN "
                "('completed', 'rejected', 'cancelled', 'expired')"
            )

        query += " ORDER BY start_time ASC, id ASC"

        with connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [_der_control_from_row(row) for row in rows]

    def list_applicable(self, device_id, current_time=None):
        timestamp = int(time.time()) if current_time is None else int(current_time)

        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM der_controls
                WHERE device_id = ?
                  AND control_status IN (
                      'scheduled',
                      'active',
                      'received',
                      'started'
                  )
                  AND (start_time + duration) > ?
                ORDER BY start_time ASC, id ASC
                """,
                (int(device_id), timestamp),
            ).fetchall()

        return [_der_control_from_row(row) for row in rows]

    def update_status(self, control_id, control_status, updated_at=None):
        self._validate_status(control_status)
        timestamp = int(time.time()) if updated_at is None else int(updated_at)

        with connect() as connection:
            cursor = connection.execute(
                """
                UPDATE der_controls
                SET control_status = ?, updated_at = ?
                WHERE id = ?
                """,
                (control_status, timestamp, int(control_id)),
            )

        if cursor.rowcount == 0:
            return None

        return self.get_by_id(control_id)

    def update_status_by_mrid(self, mrid, control_status, updated_at=None):
        control = self.get_by_mrid(mrid)

        if control is None:
            return None

        return self.update_status(
            control.id,
            control_status,
            updated_at,
        )

    def apply_response_status(self, mrid, response_status, updated_at=None):
        from .response_status import control_status_for_response, response_status_name

        control = self.get_by_mrid(mrid)

        if control is None:
            return None, None, response_status_name(response_status)

        new_status = control_status_for_response(response_status)

        if new_status is None:
            return control, control, response_status_name(response_status)


        if control.is_terminal or not self.should_apply_response_transition(control.control_status, new_status):
            return control, control, response_status_name(response_status)

        updated = self.update_status_by_mrid(
            mrid,
            new_status,
            updated_at=updated_at,
        )
        return control, updated, response_status_name(response_status)

    def should_apply_response_transition(self, current_status, new_status):
        order = {
            "scheduled": 0,
            "active": 1,
            "received": 2,
            "started": 3,
            "completed": 4,
            "rejected": 4,
            "cancelled": 4,
            "expired": 4,
            "superseded": 4,
        }
        return order.get(new_status, -1) >= order.get(current_status, -1)


    def cancel(self, mrid, cancelled_at=None):
        control = self.get_by_mrid(mrid)

        if control is None:
            return None

        if control.is_terminal:
            raise ValueError(
                f"El control {mrid} ya se encuentra en estado terminal"
            )

        timestamp = int(time.time()) if cancelled_at is None else int(cancelled_at)

        with connect() as connection:
            connection.execute(
                """
                UPDATE der_controls
                SET control_status = 'cancelled',
                    cancelled_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, control.id),
            )

        return self.get_by_id(control.id)

    def expire_due(self, current_time=None):
        timestamp = int(time.time()) if current_time is None else int(current_time)

        with connect() as connection:
            cursor = connection.execute(
                """
                UPDATE der_controls
                SET control_status = 'expired',
                    updated_at = ?
                WHERE control_status IN (
                    'scheduled',
                    'active',
                    'received',
                    'started'
                )
                  AND (start_time + duration) <= ?
                """,
                (timestamp, timestamp),
            )

        return cursor.rowcount

    @staticmethod
    def _validate_status(control_status):
        if control_status not in DER_CONTROL_STATUSES:
            raise ValueError(
                f"Estado de control invalido: {control_status}"
            )

DER_PROGRAM_REPOSITORY = DERProgramRepository()
DEFAULT_DER_CONTROL_REPOSITORY = DefaultDERControlRepository()
DER_CONTROL_REPOSITORY = DERControlRepository()
DEVICE_REPOSITORY = DeviceRepository()

MIRROR_READING_TYPES = {
    "current_rms_A",
    "voltage_rms_A",
    "voltage_current_phase_angle_A",
    "frequency",
    "active_power",
    "apparent_power",
    "reactive_power",
    "power_factor",
}

def _mirror_usage_point_from_row(row):
    if row is None:
        return None

    return MirrorUsagePointRecord(
        id=row["id"],
        device_id=row["device_id"],
        mrid=row["mrid"],
        description=row["description"],
        role_flags=row["role_flags"],
        service_category=row["service_category"],
        post_rate=row["post_rate"],
        device_lfdi=row["device_lfdi"],
        status=row["status"],
        xml_body=bytes(row["xml_body"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _mirror_meter_reading_from_row(row):
    if row is None:
        return None

    return MirrorMeterReadingRecord(
        id=row["id"],
        usage_point_id=row["usage_point_id"],
        mrid=row["mrid"],
        description=row["description"],
        reading_type=row["reading_type"],
        phase=row["phase"],
        uom=row["uom"],
        power_of_ten_multiplier=row["power_of_ten_multiplier"],
        flow_direction=row["flow_direction"],
        accumulation_behaviour=row["accumulation_behaviour"],
        commodity=row["commodity"],
        data_qualifier=row["data_qualifier"],
        kind=row["kind"],
        reading_type_xml=bytes(row["reading_type_xml"]) if row["reading_type_xml"] is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _meter_reading_from_row(row):
    if row is None:
        return None

    return MeterReadingRecord(
        id=row["id"],
        meter_reading_id=row["meter_reading_id"],
        value=row["value"],
        reading_time=row["reading_time"],
        quality_flags=row["quality_flags"],
        xml_body=bytes(row["xml_body"]),
        received_at=row["received_at"],
    )

class MirrorUsagePointRepository:
    def save(
        self,
        device_id,
        mrid,
        xml_body,
        description=None,
        role_flags=0,
        service_category=0,
        post_rate=300,
        device_lfdi=None,
        status=None,
        created_at=None,
    ):
        if not mrid or not mrid.strip():
            raise ValueError("mrid es obligatorio")

        if not isinstance(xml_body, bytes) or not xml_body:
            raise ValueError("xml_body debe contener bytes XML")

        role_flags = int(role_flags)
        service_category = int(service_category)
        post_rate = int(post_rate)

        if role_flags < 0:
            raise ValueError("role_flags no puede ser negativo")

        if not 0 <= service_category <= 255:
            raise ValueError("service_category debe estar entre 0 y 255")

        if post_rate <= 0:
            raise ValueError("post_rate debe ser mayor que cero")

        if status is not None:
            status = int(status)

            if not 0 <= status <= 255:
                raise ValueError("status debe estar entre 0 y 255")

        timestamp = int(time.time()) if created_at is None else int(created_at)
        normalized_mrid = mrid.strip().upper()
        normalized_lfdi = device_lfdi.strip().lower() if device_lfdi else None

        with connect() as connection:
            connection.execute(
                """
                INSERT INTO mirror_usage_points (
                    device_id, mrid, description, role_flags,
                    service_category, post_rate, device_lfdi, status,
                    xml_body, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id, mrid)
                DO UPDATE SET
                    description = excluded.description,
                    role_flags = excluded.role_flags,
                    service_category = excluded.service_category,
                    post_rate = excluded.post_rate,
                    device_lfdi = excluded.device_lfdi,
                    status = excluded.status,
                    xml_body = excluded.xml_body,
                    updated_at = excluded.updated_at
                """,
                (
                    int(device_id),
                    normalized_mrid,
                    description,
                    role_flags,
                    service_category,
                    post_rate,
                    normalized_lfdi,
                    status,
                    xml_body,
                    timestamp,
                    timestamp,
                ),
            )

        return self.get_by_device_and_mrid(device_id, normalized_mrid)

    def get_by_id(self, usage_point_id):
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM mirror_usage_points WHERE id = ?",
                (int(usage_point_id),),
            ).fetchone()

        return _mirror_usage_point_from_row(row)

    def get_by_device_and_mrid(self, device_id, mrid):
        with connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM mirror_usage_points
                WHERE device_id = ? AND mrid = ? COLLATE NOCASE
                """,
                (int(device_id), mrid),
            ).fetchone()

        return _mirror_usage_point_from_row(row)

    def list_for_device(self, device_id):
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM mirror_usage_points
                WHERE device_id = ?
                ORDER BY id
                """,
                (int(device_id),),
            ).fetchall()

        return [_mirror_usage_point_from_row(row) for row in rows]

    def count_for_device(self, device_id):
        with connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM mirror_usage_points
                WHERE device_id = ?
                """,
                (int(device_id),),
            ).fetchone()

        return row["total"]


class MirrorMeterReadingRepository:
    def save(
        self,
        usage_point_id,
        mrid,
        reading_type,
        description=None,
        phase=None,
        uom=None,
        power_of_ten_multiplier=0,
        flow_direction=None,
        accumulation_behaviour=None,
        commodity=None,
        data_qualifier=None,
        kind=None,
        reading_type_xml=None,
        created_at=None,
    ):
        if not mrid or not mrid.strip():
            raise ValueError("mrid es obligatorio")

        if reading_type not in MIRROR_READING_TYPES:
            raise ValueError(f"Tipo de lectura invalido: {reading_type}")

        multiplier = int(power_of_ten_multiplier)

        if not -9 <= multiplier <= 9:
            raise ValueError("power_of_ten_multiplier debe estar entre -9 y 9")

        timestamp = int(time.time()) if created_at is None else int(created_at)
        normalized_mrid = mrid.strip().upper()

        with connect() as connection:
            connection.execute(
                """
                INSERT INTO mirror_meter_readings (
                    usage_point_id, mrid, description, reading_type,
                    phase, uom, power_of_ten_multiplier, flow_direction,
                    accumulation_behaviour, commodity, data_qualifier,
                    kind, reading_type_xml, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(usage_point_id, mrid)
                DO UPDATE SET
                    description = excluded.description,
                    reading_type = excluded.reading_type,
                    phase = excluded.phase,
                    uom = excluded.uom,
                    power_of_ten_multiplier = excluded.power_of_ten_multiplier,
                    flow_direction = excluded.flow_direction,
                    accumulation_behaviour = excluded.accumulation_behaviour,
                    commodity = excluded.commodity,
                    data_qualifier = excluded.data_qualifier,
                    kind = excluded.kind,
                    reading_type_xml = excluded.reading_type_xml,
                    updated_at = excluded.updated_at
                """,
                (
                    int(usage_point_id),
                    normalized_mrid,
                    description,
                    reading_type,
                    phase,
                    int(uom) if uom is not None else None,
                    multiplier,
                    int(flow_direction) if flow_direction is not None else None,
                    int(accumulation_behaviour) if accumulation_behaviour is not None else None,
                    int(commodity) if commodity is not None else None,
                    int(data_qualifier) if data_qualifier is not None else None,
                    int(kind) if kind is not None else None,
                    reading_type_xml,
                    timestamp,
                    timestamp,
                ),
            )

        return self.get_by_usage_point_and_mrid(usage_point_id, normalized_mrid)

    def get_by_id(self, meter_reading_id):
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM mirror_meter_readings WHERE id = ?",
                (int(meter_reading_id),),
            ).fetchone()

        return _mirror_meter_reading_from_row(row)

    def get_by_usage_point_and_mrid(self, usage_point_id, mrid):
        with connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM mirror_meter_readings
                WHERE usage_point_id = ? AND mrid = ? COLLATE NOCASE
                """,
                (int(usage_point_id), mrid),
            ).fetchone()

        return _mirror_meter_reading_from_row(row)

    def list_for_usage_point(self, usage_point_id):
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM mirror_meter_readings
                WHERE usage_point_id = ?
                ORDER BY id
                """,
                (int(usage_point_id),),
            ).fetchall()

        return [_mirror_meter_reading_from_row(row) for row in rows]


class MeterReadingRepository:
    def save(
        self,
        meter_reading_id,
        value,
        reading_time,
        xml_body,
        quality_flags=None,
        received_at=None,
    ):
        if not isinstance(xml_body, bytes) or not xml_body:
            raise ValueError("xml_body debe contener bytes XML")

        timestamp = int(time.time()) if received_at is None else int(received_at)

        with connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO meter_readings (
                    meter_reading_id,
                    value,
                    reading_time,
                    quality_flags,
                    xml_body,
                    received_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(meter_reading_id),
                    int(value),
                    int(reading_time),
                    int(quality_flags) if quality_flags is not None else None,
                    xml_body,
                    timestamp,
                ),
            )
            reading_id = cursor.lastrowid

        return self.get_by_id(reading_id)

    def get_by_id(self, reading_id):
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM meter_readings WHERE id = ?",
                (int(reading_id),),
            ).fetchone()

        return _meter_reading_from_row(row)

    def list_for_meter(self, meter_reading_id, limit=100):
        limit = int(limit)

        if limit <= 0:
            raise ValueError("limit debe ser mayor que cero")

        with connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM meter_readings
                WHERE meter_reading_id = ?
                ORDER BY reading_time DESC, id DESC
                LIMIT ?
                """,
                (int(meter_reading_id), limit),
            ).fetchall()

        return [_meter_reading_from_row(row) for row in rows]

    def get_latest(self, meter_reading_id):
        readings = self.list_for_meter(meter_reading_id, limit=1)
        return readings[0] if readings else None

    def delete_older_than(self, timestamp):
        with connect() as connection:
            cursor = connection.execute(
                "DELETE FROM meter_readings WHERE reading_time < ?",
                (int(timestamp),),
            )

        return cursor.rowcount


MIRROR_USAGE_POINT_REPOSITORY = MirrorUsagePointRepository()
MIRROR_METER_READING_REPOSITORY = MirrorMeterReadingRepository()
METER_READING_REPOSITORY = MeterReadingRepository()



