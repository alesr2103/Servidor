#!/usr/bin/env python3

"""Genera una clave privada EC y una CSR para un cliente IEEE 2030.5."""

import argparse
from pathlib import Path
import subprocess
import sys


EXTENSIONS = """basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyAgreement
extendedKeyUsage = clientAuth
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer
"""


def build_parser():
    parser = argparse.ArgumentParser(description="Genera la clave privada y la CSR de un cliente IEEE 2030.5")
    parser.add_argument("--name", required=True, help="Nombre base de los archivos, por ejemplo client3")
    parser.add_argument("--directory", required=True, help="Directorio donde se crearán la clave, CSR y extensiones")
    parser.add_argument("--common-name", help="Common Name de laboratorio; por defecto utiliza el valor de --name")
    parser.add_argument("--force", action="store_true", help="Permite reemplazar archivos existentes")
    return parser


def validate_name(name):
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")

    if not name or any(character not in allowed for character in name):
        raise ValueError("El nombre solo puede contener letras, números, guion y guion bajo")

    return name


def run_command(command):
    subprocess.run(command, check=True)


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        name = validate_name(args.name.strip())
    except ValueError as exc:
        parser.error(str(exc))

    directory = Path(args.directory).expanduser().resolve()
    common_name = args.common_name.strip() if args.common_name else name

    directory.mkdir(parents=True, exist_ok=True)

    private_key = directory / f"{name}.pem"
    certificate_request = directory / f"{name}.csr"
    extensions_file = directory / f"{name}-ext.cnf"

    output_files = [private_key, certificate_request, extensions_file]
    existing_files = [path for path in output_files if path.exists()]

    if existing_files and not args.force:
        print("No se modificó ningún archivo.")
        print("Ya existen los siguientes archivos:")

        for path in existing_files:
            print(f"  {path}")

        print()
        print("Utilice otro nombre o agregue --force solamente si desea reemplazarlos.")
        return 1

    try:
        run_command(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", str(private_key)])
        private_key.chmod(0o600)

        run_command([
            "openssl",
            "req",
            "-new",
            "-key",
            str(private_key),
            "-out",
            str(certificate_request),
            "-subj",
            f"/CN={common_name}",
        ])

        extensions_file.write_text(EXTENSIONS, encoding="utf-8")
        extensions_file.chmod(0o644)

        run_command(["openssl", "pkey", "-in", str(private_key), "-check", "-noout"])
        run_command(["openssl", "req", "-in", str(certificate_request), "-noout", "-verify"])

    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: no fue posible generar la solicitud: {exc}", file=sys.stderr)
        return 1

    print()
    print("Solicitud de dispositivo creada")
    print("=" * 72)
    print(f"Nombre base:       {name}")
    print(f"Directorio:        {directory}")
    print(f"Clave privada:     {private_key}")
    print(f"CSR:               {certificate_request}")
    print(f"Extensiones:       {extensions_file}")
    print(f"Common Name:       {common_name}")
    print("=" * 72)
    print()
    print("IMPORTANTE:")
    print(f"  La clave privada {private_key.name} debe permanecer únicamente en el cliente.")
    print(f"  Entregue al servidor solamente {certificate_request.name} y {extensions_file.name}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
