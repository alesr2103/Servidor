"""Punto de entrada del mock server."""

import logging

from . import config
from .http_handler import MockHTTPServer, RequestHandler
from .store import STORE
from .tls import create_server_ssl_context
from .database import initialize_database
from .repositories import DEVICE_REPOSITORY

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("ieee2030.5.mock")


def main():
    initialize_database()
    STORE.reset()

    device = DEVICE_REPOSITORY.register_certificate(
            certificate_path=config.REGISTERED_CLIENT_CERT_FILE,
            name=config.DEFAULT_DEVICE_NAME,
            description=config.DEFAULT_DEVICE_DESCRIPTION,
            role=config.DEFAULT_DEVICE_ROLE,
    )


    client_identity = STORE.register_client_certificate(
        config.REGISTERED_CLIENT_CERT_FILE
    )

    ssl_context = None

    if config.TLS_ENABLED:
        ssl_context = create_server_ssl_context()

    server = MockHTTPServer(
        (config.HOST, config.PORT),
        RequestHandler,
        ssl_context=ssl_context,
    )

    protocol = "https" if config.TLS_ENABLED else "http"

    logger.info("=" * 72)
    
    logger.info("IEEE 2030.5 Mock Server modular")
    
    logger.info("Direccion: %s://%s:%d",protocol,config.HOST,config.PORT,)
    
    logger.info("SFDI configurado: %d", STORE.sfdi)
    logger.info("Certificado cliente requerido: %s",config.TLS_REQUIRE_CLIENT_CERTIFICATE,)

    logger.info("Cliente registrado: lfdi=%s",client_identity.lfdi_hex,)

    logger.info("Cliente registrado: sfdi=%d",client_identity.sfdi,)

    logger.info("Base de datos: %s", config.DATABASE_FILE)

    logger.info("Device ID persistente: %d", device.id)
    
    logger.info("Estado administrativo: %s", device.authorization_status)

    logger.info("DefaultDERControl: sin orden opModConnect")
    
    logger.info(
        "DERControl: opModConnect=true, start=%d, end=%d",
        STORE.control.start_time,
        STORE.control.end_time,
    )

    logger.info("Esperando conexiones...")
    logger.info("=" * 72)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Servidor detenido por el usuario.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
