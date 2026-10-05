"""Configuración TLS y extracción de identidad del cliente."""

import ssl

from . import config
from .identity import identity_from_certificate_bytes

def create_server_ssl_context():
    context = ssl.SSLContext(
            ssl.PROTOCOL_TLS_SERVER
    )

    context.minimum_version = ssl.TLSVersion.TLSv1_2 #Permite TLS1.2 o posterior

    context.set_ciphers(
        "ECDHE-ECDSA-AES128-CCM8:"
        "ECDHE-ECDSA-AES128-GCM-SHA256"
    )

    context.load_cert_chain(
        certfile=str(config.SERVER_CERT_FILE),
        keyfile=str(config.SERVER_KEY_FILE),
    )

    context.load_verify_locations(
        cafile=str(config.CA_CERT_FILE),
    )

    context.check_hostname = False

    if config.TLS_REQUIRE_CLIENT_CERTIFICATE:
        context.verify_mode = ssl.CERT_REQUIRED
    else:
        context.verify_mode = ssl.CERT_OPTIONAL

    return context

def get_peer_identity(connection):
    certificate = connection.getpeercert()

    certificate_der = connection.getpeercert(
        binary_form=True
    )

    if not certificate_der:
        raise PermissionError(
            "El cliente no presentó un certificado"
        )

    device_identity = identity_from_certificate_bytes(
        certificate_der
    )

    return {
        "certificate": certificate,
        "certificate_der": certificate_der,
        "fingerprint": (
            device_identity.fingerprint_sha256
        ),
        "lfdi": device_identity.lfdi,
        "lfdi_hex": device_identity.lfdi_hex,
        "sfdi": device_identity.sfdi,
        "tls_version": connection.version(),
        "cipher": connection.cipher(),
    }
