#!/usr/bin/env python3
"""Genera certificados EC P-256 para pruebas con el cliente EPRI."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
CERTS=ROOT/"certificados"
CSEP_ROOT=CERTS/"csep_root.pem"
EPRI_CERT=CERTS/"pti_dev.x509"
GENERATED=(CERTS/"lab-ca.key",CERTS/"lab-ca.crt",CERTS/"lab-ca.srl",CERTS/"server.key",CERTS/"server.csr",CERTS/"server.crt",CERTS/"client-trust-bundle.pem")


def run(*args):
    subprocess.run([str(arg) for arg in args],check=True)


def require(path,description):
    if not path.is_file():
        raise SystemExit(f"ERROR: falta {description}: {path}")


def remove_generated_files():
    for path in GENERATED:
        if path.exists():
            path.unlink()


def main():
    CERTS.mkdir(parents=True,exist_ok=True)
    require(CSEP_ROOT,"la CA pública CSEP requerida para autenticar al cliente EPRI")
    require(EPRI_CERT,"el certificado público del cliente EPRI")
    remove_generated_files()

    server_ext=CERTS/"server-ext.cnf"
    server_ext.write_text(
        "[server_cert]\n"
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyAgreement\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectAltName=critical,DNS:localhost,IP:127.0.0.1\n"
        "subjectKeyIdentifier=hash\n"
        "authorityKeyIdentifier=keyid,issuer\n",
        encoding="utf-8",
    )

    run("openssl","ecparam","-name","prime256v1","-genkey","-noout","-out",CERTS/"lab-ca.key")
    run("openssl","req","-x509","-new","-sha256","-days","3650","-key",CERTS/"lab-ca.key","-subj","/CN=IEEE2030.5 Laboratory CA","-addext","basicConstraints=critical,CA:TRUE","-addext","keyUsage=critical,keyCertSign,cRLSign","-addext","subjectKeyIdentifier=hash","-out",CERTS/"lab-ca.crt")

    run("openssl","ecparam","-name","prime256v1","-genkey","-noout","-out",CERTS/"server.key")
    run("openssl","req","-new","-sha256","-key",CERTS/"server.key","-subj","/CN=localhost","-out",CERTS/"server.csr")
    run("openssl","x509","-req","-sha256","-days","825","-in",CERTS/"server.csr","-CA",CERTS/"lab-ca.crt","-CAkey",CERTS/"lab-ca.key","-CAcreateserial","-extfile",server_ext,"-extensions","server_cert","-out",CERTS/"server.crt")

    shutil.copyfile(CSEP_ROOT,CERTS/"client-trust-bundle.pem")

    if sys.platform != "win32":
        (CERTS/"lab-ca.key").chmod(0o600)
        (CERTS/"server.key").chmod(0o600)

    print("OK: certificados de laboratorio generados")
    print(f"CA para verificar el servidor: {CERTS/'lab-ca.crt'}")
    print(f"Certificado del servidor: {CERTS/'server.crt'}")
    print(f"Clave privada del servidor: {CERTS/'server.key'}")
    print(f"CA confiable para el cliente EPRI: {CERTS/'client-trust-bundle.pem'}")
    print(f"Certificado EPRI registrado: {EPRI_CERT}")


if __name__ == "__main__":
    main()
