"""Aprueba una CSR, emite el certificado y registra el dispositivo DER."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from . import config
from .database import initialize_database
from .repositories import DEVICE_REPOSITORY


def positive_integer(value):
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("El valor debe ser un número entero") from exc

    if number <= 0:
        raise argparse.ArgumentTypeError("El valor debe ser mayor que cero")

    return number


def build_parser():
    parser = argparse.ArgumentParser(description="Firma una CSR y registra un dispositivo DER")
    parser.add_argument("--csr", required=True, help="Ruta de la solicitud CSR")
    parser.add_argument("--extensions", required=True, help="Ruta del archivo de extensiones OpenSSL")
    parser.add_argument("--name", required=True, help="Nombre administrativo del dispositivo")
    parser.add_argument("--description", default="", help="Descripción administrativa opcional")
    parser.add_argument("--role", choices=("device", "aggregator"), default="device", help="Rol del cliente")
    parser.add_argument("--status", choices=("pending", "active", "blocked", "retired"), default="active", help="Estado administrativo inicial")
    parser.add_argument("--pin", type=positive_integer, default=config.REGISTRATION_PIN, help="PIN de Registration")
    parser.add_argument("--poll-rate", type=positive_integer, default=config.REGISTRATION_POLL_RATE, help="Poll rate de Registration")
    parser.add_argument("--days", type=positive_integer, default=825, help="Validez del certificado en días")
    parser.add_argument("--output", required=True, help="Directorio donde se copiarán los certificados emitidos")
    parser.add_argument("--force", action="store_true", help="Permite reemplazar certificados públicos existentes")
    return parser


def run_command(command):
    subprocess.run(command, check=True)


def certificate_name_from_csr(csr_path):
    name = csr_path.stem

    if not name:
        raise ValueError("No fue posible determinar el nombre base de la CSR")

    return name


def print_device(device, certificate_pem, certificate_der, ca_file):
    print()
    print("Dispositivo aprobado y registrado")
    print("=" * 72)
    print(f"Device ID:             {device.id}")
    print(f"Nombre:                {device.name}")
    print(f"Descripción:           {device.description or '(sin descripción)'}")
    print(f"Rol:                   {device.role}")
    print(f"LFDI:                  {device.lfdi}")
    print(f"SFDI:                  {device.sfdi}")
    print(f"Fingerprint SHA-256:   {device.fingerprint_sha256}")
    print(f"Estado:                {device.authorization_status}")
    print(f"Habilitado:            {device.enabled}")
    print(f"Certificado PEM:       {certificate_pem}")
    print(f"Certificado DER:       {certificate_der}")
    print(f"CA del servidor:       {ca_file}")
    print(f"EndDevice URI:         {device.end_device_href}")
    print(f"Registration URI:      {device.registration_href}")
    print(f"DERList URI:           {device.der_list_href}")
    print("=" * 72)


def main():
    parser = build_parser()
    args = parser.parse_args()

    csr_path = Path(args.csr).expanduser().resolve()
    extensions_path = Path(args.extensions).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()

    if not csr_path.is_file():
        parser.error(f"La CSR no existe: {csr_path}")

    if not extensions_path.is_file():
        parser.error(f"El archivo de extensiones no existe: {extensions_path}")

    if not config.CA_CERT_FILE.is_file():
        parser.error(f"No existe el certificado de confianza configurado: {config.CA_CERT_FILE}")

    lab_ca_certificate = config.CERTIFICATES_DIR / "lab-ca.crt"
    lab_ca_private_key = config.CERTIFICATES_DIR / "lab-ca.key"

    if not lab_ca_certificate.is_file():
        parser.error(f"No existe la CA de laboratorio: {lab_ca_certificate}")

    if not lab_ca_private_key.is_file():
        parser.error(f"No existe la clave privada de la CA: {lab_ca_private_key}")

    output_dir.mkdir(parents=True, exist_ok=True)
    certificate_name = certificate_name_from_csr(csr_path)
    output_pem = output_dir / f"{certificate_name}.crt"
    output_der = output_dir / f"{certificate_name}.x509"
    output_ca_dir = output_dir / "certs"
    output_ca = output_ca_dir / "lab-ca.crt"

    existing_outputs = [path for path in (output_pem, output_der) if path.exists()]

    if existing_outputs and not args.force:
        print("No se emitió ningún certificado.")
        print("Ya existen los siguientes archivos:")

        for path in existing_outputs:
            print(f"  {path}")

        print()
        print("Utilice otro cliente o agregue --force solo si desea reemplazar los certificados públicos.")
        return 1

    try:
        run_command(["openssl", "req", "-in", str(csr_path), "-noout", "-verify"])

        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            temporary_pem = temporary_path / f"{certificate_name}.crt"
            temporary_der = temporary_path / f"{certificate_name}.x509"

            run_command([
                "openssl",
                "x509",
                "-req",
                "-in",
                str(csr_path),
                "-CA",
                str(lab_ca_certificate),
                "-CAkey",
                str(lab_ca_private_key),
                "-CAcreateserial",
                "-out",
                str(temporary_pem),
                "-days",
                str(args.days),
                "-sha256",
                "-extfile",
                str(extensions_path),
            ])

            run_command([
                "openssl",
                "verify",
                "-purpose",
                "sslclient",
                "-CAfile",
                str(lab_ca_certificate),
                str(temporary_pem),
            ])

            run_command([
                "openssl",
                "x509",
                "-in",
                str(temporary_pem),
                "-outform",
                "DER",
                "-out",
                str(temporary_der),
            ])

            initialize_database()

            device = DEVICE_REPOSITORY.register_certificate(
                certificate_path=temporary_der,
                name=args.name.strip(),
                description=args.description.strip(),
                role=args.role,
                pin=args.pin,
                poll_rate=args.poll_rate,
            )

            if device.authorization_status != args.status:
                DEVICE_REPOSITORY.set_authorization_status(device.id, args.status)
                device = DEVICE_REPOSITORY.find_by_id(device.id)

            shutil.copy2(temporary_pem, output_pem)
            shutil.copy2(temporary_der, output_der)

        output_ca_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(lab_ca_certificate, output_ca)

    except (OSError, ValueError, LookupError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: no fue posible aprobar el dispositivo: {exc}", file=sys.stderr)
        return 1

    print_device(device, output_pem, output_der, output_ca)
    print()
    print("La clave privada permanece en el cliente y no fue copiada al servidor.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
