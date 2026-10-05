#!/usr/bin/env python3

from mock_server import config
from mock_server.database import initialize_database
from mock_server.repositories import DEFAULT_DER_CONTROL_REPOSITORY, DER_PROGRAM_REPOSITORY
from mock_server.xsd_validator import SEP_XML_VALIDATOR

DEVICE_ID = 1
PROGRAM_MRID = config.DER_PROGRAM_MRID
DEFAULT_MRID = config.DEFAULT_CONTROL_MRID


def default_control_xml():
    return (
        f'<DefaultDERControl xmlns="{config.NAMESPACE}">'
        f'<mRID>{DEFAULT_MRID}</mRID>'
        f'<description>Control DER por defecto</description>'
        f'<version>1</version>'
        f'<DERControlBase/>'
        f'</DefaultDERControl>'
    ).encode()


def main():
    initialize_database()
    program = DER_PROGRAM_REPOSITORY.get_by_mrid(PROGRAM_MRID)

    if program is None:
        program = DER_PROGRAM_REPOSITORY.save(
            device_id=DEVICE_ID,
            mrid=PROGRAM_MRID,
            description="Programa DER principal",
            version=1,
            primacy=0,
            active=True,
        )
        print(f"Programa creado: id={program.id} mrid={program.mrid}")
    else:
        print(f"Programa existente: id={program.id} mrid={program.mrid}")

    body = default_control_xml()
    SEP_XML_VALIDATOR.validate(body)
    control = DEFAULT_DER_CONTROL_REPOSITORY.save(
        program_id=program.id,
        mrid=DEFAULT_MRID,
        description="Control DER por defecto",
        version=1,
        control_xml=body,
    )
    print(f"DefaultDERControl listo: id={control.id} mrid={control.mrid}")


if __name__ == "__main__":
    main()
