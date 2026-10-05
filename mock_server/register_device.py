"""Herramienta administrativa para registrar dispositivos DER."""

import argparse
import logging
from pathlib import Path
import sys

from . import config
from .database import initialize_database
from .repositories import DEVICE_REPOSITORY


logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("ieee2030.5.register_device")


def positive_integer(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("El valor debe ser un número entero") from exc

    if number <= 0:
        raise argparse.ArgumentTypeError("El valor debe ser mayor que cero")

    return number


def build_parser():
    parser = argparse.ArgumentParser(description="Registra un dispositivo DER mediante su certificado público")
    parser.add_argument("--certificate", required=True, help="Ruta del certificado público PEM, CRT o X509/DER")
    parser.add_argument("--name", required=True, help="Nombre administrativo del dispositivo")
    parser.add_argument("--description", default="", help="Descripción administrativa opcional")
    parser.add_argument("--role", choices=("device", "aggregator"), default="device", help="Rol del cliente IEEE 2030.5")
    parser.add_argument("--status", choices=("pending", "active", "blocked", "retired"), default="active", help="Estado administrativo inicial")
    parser.add_argument("--pin", type=positive_integer, default=config.REGISTRATION_PIN, help="PIN del recurso Registration")
    parser.add_argument("--poll-rate", type=positive_integer, default=config.REGISTRATION_POLL_RATE, help="Intervalo de consulta de Registration en segundos")
    return parser


def print_device(device):
    print()
    print("Dispositivo registrado")
    print("=" * 72)
    print(f"ID:                     {device.id}")
    print(f"Nombre:                 {device.name}")
    print(f"Descripción:            {device.description or '(sin descripción)'}")
    print(f"Rol:                    {device.role}")
    print(f"LFDI:                   {device.lfdi}")
    print(f"SFDI:                   {device.sfdi}")
    print(f"Fingerprint SHA-256:    {device.fingerprint_sha256}")
    print(f"Estado administrativo: {device.authorization_status}")
    print(f"Habilitado:             {device.enabled}")
    print(f"Fecha de registro:      {device.registered_at}")
    print(f"EndDevice URI:          {device.end_device_href}")
    print(f"Registration URI:       {device.registration_href}")
    print(f"DERList URI:            {device.der_list_href}")
    print("=" * 72)


def main():
    parser = build_parser()
    args = parser.parse_args()

    certificate_path = Path(args.certificate).expanduser().resolve()

    if not certificate_path.is_file():
        parser.error(f"El certificado no existe o no es un archivo: {certificate_path}")

    if certificate_path.suffix.lower() in {".key", ".pem"} and "key" in certificate_path.name.lower():
        parser.error("Debe registrar el certificado público, no una clave privada")

    initialize_database()

    try:
        device = DEVICE_REPOSITORY.register_certificate(
            certificate_path=certificate_path,
            name=args.name.strip(),
            description=args.description.strip(),
            role=args.role,
            pin=args.pin,
            poll_rate=args.poll_rate,
        )

        if device.authorization_status != args.status:
            DEVICE_REPOSITORY.set_authorization_status(device.id, args.status)
            device = DEVICE_REPOSITORY.find_by_id(device.id)

    except (OSError, ValueError, LookupError) as exc:
        logger.error("No fue posible registrar el dispositivo: %s", exc)
        return 1

    print_device(device)
    return 0


if __name__ == "__main__":
    sys.exit(main())
