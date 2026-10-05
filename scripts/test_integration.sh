#!/usr/bin/env bash

set -u
set -o pipefail

PROJECT_DIR="${HOME}/Servidor"
EPRI_DIR="${HOME}/IEEE-2030.5-Client"

SERVER_URL="https://127.0.0.1:8443"
SERVER_CA="${PROJECT_DIR}/certificados/lab-ca.crt"

EPRI_CERT_DER="${EPRI_DIR}/pti_dev.x509"
EPRI_CERT_PEM="/tmp/pti_dev.crt"
EPRI_KEY="${EPRI_DIR}/pti_dev.pem"

REGISTERED_SFDI="17298934539"

PASS_COUNT=0
FAIL_COUNT=0


pass()
{
    printf '[OK] %s\n' "$1"
    PASS_COUNT=$((PASS_COUNT + 1))
}


fail()
{
    printf '[ERROR] %s\n' "$1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}


require_file()
{
    if test -f "$1"; then
        pass "Existe $1"
    else
        fail "No existe $1"
        return 1
    fi
}


echo "============================================================"
echo "Pruebas de integración del Mock Server IEEE 2030.5"
echo "============================================================"


echo
echo "1. Verificando archivos requeridos"

require_file "${SERVER_CA}" || exit 1
require_file "${EPRI_CERT_DER}" || exit 1
require_file "${EPRI_KEY}" || exit 1


echo
echo "2. Verificando que el servidor esté escuchando"

if ss -lnt | grep -q ':8443 '; then
    pass "El servidor escucha en el puerto 8443"
else
    fail "El servidor no escucha en el puerto 8443"
    echo
    echo "Inícielo en otra terminal con:"
    echo "  cd ${PROJECT_DIR}"
    echo "  python3 -m mock_server.app"
    exit 1
fi


echo
echo "3. Convirtiendo el certificado EPRI de DER a PEM"

if openssl x509 \
    -inform DER \
    -in "${EPRI_CERT_DER}" \
    -out "${EPRI_CERT_PEM}"
then
    pass "Certificado EPRI convertido a PEM"
else
    fail "No fue posible convertir el certificado EPRI"
    exit 1
fi


echo
echo "4. Verificando TLS 1.2 y CCM8"

TLS_OUTPUT=$(
    openssl s_client \
        -tls1_2 \
        -connect 127.0.0.1:8443 \
        -CAfile "${SERVER_CA}" \
        -cert "${EPRI_CERT_PEM}" \
        -key "${EPRI_KEY}" \
        -cipher ECDHE-ECDSA-AES128-CCM8 \
        -verify_return_error \
        < /dev/null 2>&1
)

if printf '%s\n' "${TLS_OUTPUT}" |
    grep -q 'ECDHE-ECDSA-AES128-CCM8'
then
    pass "Suite ECDHE-ECDSA-AES128-CCM8 negociada"
else
    fail "No se negoció ECDHE-ECDSA-AES128-CCM8"
fi

if printf '%s\n' "${TLS_OUTPUT}" |
    grep -q 'Verify return code: 0'
then
    pass "Cadena del servidor verificada correctamente"
else
    fail "La verificación del certificado servidor falló"
fi

if printf '%s\n' "${TLS_OUTPUT}" |
    grep -q 'TLSv1.2'
then
    pass "TLS 1.2 negociado correctamente"
else
    fail "No se confirmó TLS 1.2"
fi


echo
echo "5. Verificando GET /dcap"

DCAP_HTTP_CODE=$(
    curl \
        --silent \
        --show-error \
        --output /tmp/dcap-integration.xml \
        --write-out '%{http_code}' \
        --tlsv1.2 \
        --tls-max 1.2 \
        --ciphers ECDHE-ECDSA-AES128-CCM8 \
        --cacert "${SERVER_CA}" \
        --cert "${EPRI_CERT_PEM}" \
        --key "${EPRI_KEY}" \
        "${SERVER_URL}/dcap"
)

if test "${DCAP_HTTP_CODE}" = "200"; then
    pass "GET /dcap respondió HTTP 200"
else
    fail "GET /dcap respondió HTTP ${DCAP_HTTP_CODE}"
fi


echo
echo "6. Verificando XML de DeviceCapability"

if xmllint --noout /tmp/dcap-integration.xml 2>/dev/null; then
    pass "DeviceCapability es XML bien formado"
else
    fail "DeviceCapability contiene XML inválido"
fi

DCAP_ROOT=$(
    xmllint \
        --xpath 'local-name(/*)' \
        /tmp/dcap-integration.xml \
        2>/dev/null
)

if test "${DCAP_ROOT}" = "DeviceCapability"; then
    pass "El elemento raíz es DeviceCapability"
else
    fail "El elemento raíz es ${DCAP_ROOT}"
fi

DCAP_NAMESPACE=$(
    xmllint \
        --xpath 'namespace-uri(/*)' \
        /tmp/dcap-integration.xml \
        2>/dev/null
)

if test "${DCAP_NAMESPACE}" = "http://ieee.org/2030.5"; then
    pass "Namespace IEEE 2030.5 correcto"
else
    fail "Namespace incorrecto: ${DCAP_NAMESPACE}"
fi


echo
echo "7. Verificando EndDevice y SFDI"

EDEV_HTTP_CODE=$(
    curl \
        --silent \
        --show-error \
        --output /tmp/edev-integration.xml \
        --write-out '%{http_code}' \
        --tlsv1.2 \
        --tls-max 1.2 \
        --ciphers ECDHE-ECDSA-AES128-CCM8 \
        --cacert "${SERVER_CA}" \
        --cert "${EPRI_CERT_PEM}" \
        --key "${EPRI_KEY}" \
        "${SERVER_URL}/edev"
)

if test "${EDEV_HTTP_CODE}" = "200"; then
    pass "GET /edev respondió HTTP 200"
else
    fail "GET /edev respondió HTTP ${EDEV_HTTP_CODE}"
fi

RECEIVED_SFDI=$(
    xmllint \
        --xpath \
        'string(/*[local-name()="EndDeviceList"]/*[local-name()="EndDevice"]/*[local-name()="sFDI"])' \
        /tmp/edev-integration.xml \
        2>/dev/null
)

if test "${RECEIVED_SFDI}" = "${REGISTERED_SFDI}"; then
    pass "SFDI correcto: ${RECEIVED_SFDI}"
else
    fail \
        "SFDI incorrecto. Esperado=${REGISTERED_SFDI}, recibido=${RECEIVED_SFDI}"
fi


echo
echo "8. Verificando recursos principales"

ROUTES="
/dcap
/tm
/edev
/edev/1
/edev/1/der
/edev/1/der/1
/edev/1/fsa
/edev/1/fsa/1
/edev/1/fsa/1/derp
/edev/1/fsa/1/derp/1
/edev/1/fsa/1/derp/1/dderc
/edev/1/fsa/1/derp/1/derc
"

for route in ${ROUTES}
do
    HTTP_CODE=$(
        curl \
            --silent \
            --show-error \
            --output /tmp/resource-integration.xml \
            --write-out '%{http_code}' \
            --tlsv1.2 \
            --tls-max 1.2 \
            --ciphers ECDHE-ECDSA-AES128-CCM8 \
            --cacert "${SERVER_CA}" \
            --cert "${EPRI_CERT_PEM}" \
            --key "${EPRI_KEY}" \
            "${SERVER_URL}${route}"
    )

    if test "${HTTP_CODE}" = "200"; then
        pass "${route} respondió HTTP 200"
    else
        fail "${route} respondió HTTP ${HTTP_CODE}"
    fi
done


echo
echo "============================================================"
echo "Resultado"
echo "============================================================"
echo "Pruebas correctas: ${PASS_COUNT}"
echo "Pruebas fallidas:  ${FAIL_COUNT}"

if test "${FAIL_COUNT}" -eq 0; then
    echo
    echo "INTEGRACIÓN CORRECTA"
    exit 0
fi

echo
echo "INTEGRACIÓN CON ERRORES"
exit 1
