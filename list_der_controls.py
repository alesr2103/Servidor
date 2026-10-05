#!/usr/bin/env python3

import argparse
from datetime import datetime

from mock_server.repositories import DER_CONTROL_REPOSITORY


def local_time(timestamp):
    return datetime.fromtimestamp(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def main():
    parser = argparse.ArgumentParser(description="Listar controles DER persistentes")
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--active-only", action="store_true")
    args = parser.parse_args()

    controls = DER_CONTROL_REPOSITORY.list_for_device(
        args.device_id,
        include_terminal=not args.active_only,
    )

    if not controls:
        print("No existen controles DER")
        return

    print(f"{'ID':<5} {'mRID':<18} {'estado':<11} {'inicio':<20} {'fin':<20} {'duracion':<8}")

    for control in controls:
        print(
            f"{control.id:<5} "
            f"{control.mrid:<18} "
            f"{control.control_status:<11} "
            f"{local_time(control.start_time):<20} "
            f"{local_time(control.end_time):<20} "
            f"{control.duration:<8}"
        )


if __name__ == "__main__":
    main()
