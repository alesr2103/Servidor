#!/usr/bin/env python3

import argparse
import secrets
import time

from mock_server import config
from mock_server.repositories import AUDIT_EVENT_REPOSITORY, DER_CONTROL_REPOSITORY, DER_PROGRAM_REPOSITORY
from mock_server.xsd_validator import SEP_XML_VALIDATOR


def parse_bool(value):
    normalized = value.strip().lower()

    if normalized in {"true", "1", "yes", "si"}:
        return True

    if normalized in {"false", "0", "no"}:
        return False

    raise argparse.ArgumentTypeError("Use true o false")


def build_xml(mrid, description, creation_time, start_time, duration, connect):
    connect_xml = f"<opModConnect>{str(connect).lower()}</opModConnect>"

    return (
        f'<DERControl xmlns="{config.NAMESPACE}" replyTo="/rsps/1/rsp" responseRequired="03">'
        f"<mRID>{mrid}</mRID>"
        f"<description>{description}</description>"
        f"<version>1</version>"
        f"<creationTime>{creation_time}</creationTime>"
        f"<EventStatus>"
        f"<currentStatus>0</currentStatus>"
        f"<dateTime>{creation_time}</dateTime>"
        f"<potentiallySuperseded>false</potentiallySuperseded>"
        f"</EventStatus>"
        f"<interval><duration>{duration}</duration><start>{start_time}</start></interval>"
        f"<DERControlBase>{connect_xml}</DERControlBase>"
        f"</DERControl>"
    ).encode()


def main():
    parser = argparse.ArgumentParser(description="Crear un DERControl persistente")
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--start-in", type=int, default=60)
    parser.add_argument("--duration", type=int, default=120)
    parser.add_argument("--connect", type=parse_bool, default=True)
    parser.add_argument("--description", default="Control DER temporal")
    parser.add_argument("--mrid")
    args = parser.parse_args()

    if args.start_in < 0:
        parser.error("--start-in no puede ser negativo")

    if args.duration <= 0:
        parser.error("--duration debe ser mayor que cero")

    program = DER_PROGRAM_REPOSITORY.get_active_for_device(args.device_id)

    if program is None:
        raise SystemExit(
            f"No existe un DERProgram activo para device_id={args.device_id}. "
            "Ejecute initialize_der_control_data.py"
        )

    creation_time = int(time.time())
    start_time = creation_time + args.start_in
    mrid = args.mrid or secrets.token_hex(8).upper()

    if DER_CONTROL_REPOSITORY.get_by_mrid(mrid) is not None:
        raise SystemExit(f"Ya existe un control con mRID={mrid}")

    body = build_xml(
        mrid,
        args.description,
        creation_time,
        start_time,
        args.duration,
        args.connect,
    )
    SEP_XML_VALIDATOR.validate(body)

    control = DER_CONTROL_REPOSITORY.save(
        program_id=program.id,
        device_id=args.device_id,
        mrid=mrid,
        description=args.description,
        version=1,
        creation_time=creation_time,
        start_time=start_time,
        duration=args.duration,
        control_xml=body,
        control_status="scheduled",
    )

    AUDIT_EVENT_REPOSITORY.save(
        device_id=args.device_id,
        event_category="control",
        event_type="der_control_created",
        severity="info",
        resource_type="DERControl",
        subject=control.mrid,
        details=f"Control creado: start={control.start_time} duration={control.duration}",
    )

    print(f"id={control.id}")
    print(f"mrid={control.mrid}")
    print(f"status={control.control_status}")
    print(f"start_time={control.start_time}")
    print(f"end_time={control.end_time}")
    print(f"duration={control.duration}")


if __name__ == "__main__":
    main()
