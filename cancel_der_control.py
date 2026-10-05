#!/usr/bin/env python3

import argparse

from mock_server.repositories import AUDIT_EVENT_REPOSITORY, DER_CONTROL_REPOSITORY


def main():
    parser = argparse.ArgumentParser(description="Cancelar un DERControl persistente")
    parser.add_argument("--mrid", required=True)
    args = parser.parse_args()

    control = DER_CONTROL_REPOSITORY.get_by_mrid(args.mrid)

    if control is None:
        raise SystemExit(f"No existe DERControl con mRID={args.mrid}")

    try:
        cancelled = DER_CONTROL_REPOSITORY.cancel(args.mrid)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    AUDIT_EVENT_REPOSITORY.save(
        device_id=cancelled.device_id,
        event_category="control",
        event_type="der_control_cancelled",
        severity="info",
        resource_type="DERControl",
        subject=cancelled.mrid,
        details="Control cancelado administrativamente",
    )

    print(f"id={cancelled.id}")
    print(f"mrid={cancelled.mrid}")
    print(f"status={cancelled.control_status}")
    print(f"cancelled_at={cancelled.cancelled_at}")


if __name__ == "__main__":
    main()
