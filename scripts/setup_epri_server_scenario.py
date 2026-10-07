#!/usr/bin/env python3

import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT_DIR=Path(__file__).resolve().parents[1]
DATABASE=PROJECT_DIR/"data"/"server.db"

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from mock_server.xsd_validator import SEP_XML_VALIDATOR

NAMESPACE = "http://ieee.org/2030.5"
DATABASE = Path.home() / "Servidor" / "data" / "server.db"

PROGRAM_1_MRID = "A1000000000000000000000000000001"
PROGRAM_2_MRID = "A1000000000000000000000000000002"

DEFAULT_1_MRID = "D1000000000000000000000000000001"
DEFAULT_2_MRID = "D1000000000000000000000000000002"

EVENT_1_MRID = "E1000000000000000000000000000001"
EVENT_2_MRID = "E1000000000000000000000000000002"

ET.register_namespace("", NAMESPACE)


def element(name, attributes=None):
    return ET.Element(
        f"{{{NAMESPACE}}}{name}",
        attributes or {},
    )


def child(parent, name, value=None):
    node = ET.SubElement(
        parent,
        f"{{{NAMESPACE}}}{name}",
    )

    if value is not None:
        node.text = str(value)

    return node


def serialize(root):
    return ET.tostring(
        root,
        encoding="utf-8",
        xml_declaration=False,
    )


def add_fixed_pf(parent, displacement, multiplier):
    fixed_pf = child(parent, "opModFixedPF")
    child(fixed_pf, "displacement", displacement)
    child(fixed_pf, "multiplier", multiplier)


def default_control_xml(
    mrid,
    description,
    displacement,
    multiplier=-3,
):
    root = element("DefaultDERControl")
    child(root, "mRID", mrid)
    child(root, "description", description)
    child(root, "version", 1)

    base = child(root, "DERControlBase")
    add_fixed_pf(base, displacement, multiplier)

    body = serialize(root)
    SEP_XML_VALIDATOR.validate(body)
    return body


def event_control_xml(
    mrid,
    description,
    creation_time,
    start_time,
    duration,
    displacement,
    multiplier=-3,
):
    root = element(
        "DERControl",
        {
            "replyTo": "/rsps/1/rsp",
            "responseRequired": "03",
        },
    )
    child(root, "mRID", mrid)
    child(root, "description", description)
    child(root, "version", 1)
    child(root, "creationTime", creation_time)

    status = child(root, "EventStatus")
    child(status, "currentStatus", 0)
    child(status, "dateTime", creation_time)
    child(status, "potentiallySuperseded", "false")

    interval = child(root, "interval")
    child(interval, "duration", duration)
    child(interval, "start", start_time)

    base = child(root, "DERControlBase")
    add_fixed_pf(base, displacement, multiplier)

    body = serialize(root)
    SEP_XML_VALIDATOR.validate(body)
    return body


def save_program(
    connection,
    program_id,
    mrid,
    description,
    primacy,
    timestamp,
):
    connection.execute(
        """
        INSERT INTO der_programs (
            id,
            device_id,
            mrid,
            description,
            version,
            primacy,
            active,
            created_at,
            updated_at
        )
        VALUES (?, 1, ?, ?, 1, ?, 1, ?, ?)
        ON CONFLICT(id)
        DO UPDATE SET
            device_id = 1,
            mrid = excluded.mrid,
            description = excluded.description,
            version = excluded.version,
            primacy = excluded.primacy,
            active = 1,
            updated_at = excluded.updated_at
        """,
        (
            program_id,
            mrid,
            description,
            primacy,
            timestamp,
            timestamp,
        ),
    )


def save_default(
    connection,
    program_id,
    mrid,
    description,
    control_xml,
    timestamp,
):
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
        VALUES (?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(program_id)
        DO UPDATE SET
            mrid = excluded.mrid,
            description = excluded.description,
            version = excluded.version,
            control_xml = excluded.control_xml,
            updated_at = excluded.updated_at
        """,
        (
            program_id,
            mrid,
            description,
            control_xml,
            timestamp,
            timestamp,
        ),
    )


def save_event(
    connection,
    program_id,
    mrid,
    description,
    creation_time,
    start_time,
    duration,
    control_xml,
    timestamp,
):
    connection.execute(
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
        VALUES (
            ?,
            1,
            ?,
            ?,
            1,
            ?,
            ?,
            ?,
            'scheduled',
            ?,
            NULL,
            ?,
            ?
        )
        """,
        (
            program_id,
            mrid,
            description,
            creation_time,
            start_time,
            duration,
            control_xml,
            timestamp,
            timestamp,
        ),
    )


def main():
    now = int(time.time())

    event_1_start = now + 30
    event_2_start = now + 90
    duration = 30

    default_1 = default_control_xml(
        DEFAULT_1_MRID,
        "DDERC baja prioridad PF 0.950",
        950,
    )
    default_2 = default_control_xml(
        DEFAULT_2_MRID,
        "DDERC alta prioridad PF 0.980",
        980,
    )

    event_1 = event_control_xml(
        EVENT_1_MRID,
        "Evento 1 PF 0.900",
        now,
        event_1_start,
        duration,
        900,
    )
    event_2 = event_control_xml(
        EVENT_2_MRID,
        "Evento 2 PF -0.900",
        now,
        event_2_start,
        duration,
        -900,
    )

    connection = sqlite3.connect(DATABASE)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")

        connection.execute(
            "DELETE FROM control_responses WHERE device_id = 1"
        )
        connection.execute(
            "DELETE FROM der_controls WHERE device_id = 1"
        )

        save_program(
            connection,
            1,
            PROGRAM_1_MRID,
            "DERProgram baja prioridad",
            10,
            now,
        )
        save_program(
            connection,
            2,
            PROGRAM_2_MRID,
            "DERProgram alta prioridad",
            0,
            now,
        )

        save_default(
            connection,
            1,
            DEFAULT_1_MRID,
            "DDERC baja prioridad PF 0.950",
            default_1,
            now,
        )
        save_default(
            connection,
            2,
            DEFAULT_2_MRID,
            "DDERC alta prioridad PF 0.980",
            default_2,
            now,
        )

        save_event(
            connection,
            1,
            EVENT_1_MRID,
            "Evento 1 PF 0.900",
            now,
            event_1_start,
            duration,
            event_1,
            now,
        )
        save_event(
            connection,
            2,
            EVENT_2_MRID,
            "Evento 2 PF -0.900",
            now,
            event_2_start,
            duration,
            event_2,
            now,
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    print("ESCENARIO EPRI CONFIGURADO")
    print()
    print("Programa 1")
    print("  ID: 1")
    print("  primacy: 10")
    print("  prioridad: baja")
    print("  default PF: 0.950")
    print(f"  evento inicia: {event_1_start}")
    print("  evento PF: 0.900")
    print("  duracion: 30 segundos")
    print()
    print("Programa 2")
    print("  ID: 2")
    print("  primacy: 0")
    print("  prioridad: alta")
    print("  default PF: 0.980")
    print(f"  evento inicia: {event_2_start}")
    print("  evento PF: -0.900")
    print("  duracion: 30 segundos")
    print()
    print("Ejecute el cliente inmediatamente.")
    print("Los eventos comienzan 30 y 90 segundos despues de esta configuracion.")


if __name__ == "__main__":
    main()
