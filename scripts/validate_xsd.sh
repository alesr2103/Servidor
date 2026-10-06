#!/usr/bin/env bash

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CLIENT_DIR="${EPRI_CLIENT_DIR:-$HOME/Cliente-2030.5}"
SERVER_URL="https://127.0.0.1:8443"
SERVER_CA="$PROJECT_DIR/certificados/lab-ca.crt"
CLIENT_CERT_DER="$CLIENT_DIR/pti_dev.x509"
CLIENT_CERT_PEM="/tmp/pti_dev-validation.crt"
CLIENT_KEY="$CLIENT_DIR/pti_dev.pem"
SCHEMA="$CLIENT_DIR/sep.xsd"
OUTPUT_DIR="/tmp/ieee20305-xsd"
CONTROL_LIST_FILE="$OUTPUT_DIR/der-control-list.xml"
MUP_LIST_FILE="$OUTPUT_DIR/mirror-usage-point-list.xml"

PASS_COUNT=0
FAIL_COUNT=0
SKIP_COUNT=0

pass() {
    printf '[OK] %s\n' "$1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    printf '[ERROR] %s\n' "$1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

skip() {
    printf '[OMITIDO] %s\n' "$1"
    SKIP_COUNT=$((SKIP_COUNT + 1))
}

request_route() {
    route="$1"
    output="$2"

    curl --silent --show-error \
        --output "$output" \
        --write-out '%{http_code}' \
        --tlsv1.2 \
        --tls-max 1.2 \
        --ciphers ECDHE-ECDSA-AES128-CCM8 \
        --cacert "$SERVER_CA" \
        --cert "$CLIENT_CERT_PEM" \
        --key "$CLIENT_KEY" \
        "$SERVER_URL$route"
}

validate_route() {
    route="$1"
    name="$2"
    output="$OUTPUT_DIR/$name.xml"
    http_code=$(request_route "$route" "$output")

    if test "$http_code" != "200"; then
        fail "$route respondió HTTP $http_code"
        return 1
    fi

    pass "$route respondió HTTP 200"

    if ! xmllint --noout "$output" 2>"$output.wellformed.log"; then
        fail "$route contiene XML mal formado"
        cat "$output.wellformed.log"
        return 1
    fi

    pass "$route contiene XML bien formado"

    if xmllint --noout --schema "$SCHEMA" "$output" 2>"$output.schema.log"; then
        pass "$route valida contra sep.xsd"
    else
        fail "$route no valida contra sep.xsd"
        sed -n '1,15p' "$output.schema.log"
        return 1
    fi

    return 0
}

extract_routes() {
    file="$1"
    element_name="$2"

    python3 - "$file" "$element_name" <<'PY'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
element_name = sys.argv[2]
routes = []

for element in root.iter():
    if element.tag.rsplit("}", 1)[-1] != element_name:
        continue

    href = element.get("href")

    if href and href not in routes:
        routes.append(href)

for route in routes:
    print(route)
PY
}

validate_dynamic_controls() {
    if ! test -s "$CONTROL_LIST_FILE"; then
        fail "No existe DERControlList para extraer rutas dinámicas"
        return
    fi

    control_routes=$(extract_routes "$CONTROL_LIST_FILE" "DERControl")

    if test -z "$control_routes"; then
        pass "DERControlList no contiene controles vigentes"
        return
    fi

    control_number=0

    while IFS= read -r route; do
        test -z "$route" && continue
        control_number=$((control_number + 1))
        validate_route "$route" "der-control-$control_number"
    done <<EOF
$control_routes
EOF
}

validate_meter_readings() {
    mup_route="$1"
    mup_number="$2"
    meter_list_route="$mup_route/mr"
    meter_list_name="mirror-meter-reading-list-$mup_number"
    meter_list_file="$OUTPUT_DIR/$meter_list_name.xml"

    validate_route "$meter_list_route" "$meter_list_name" || return

    meter_routes=$(extract_routes "$meter_list_file" "MirrorMeterReading")

    if test -z "$meter_routes"; then
        pass "$meter_list_route no contiene definiciones de medición"
        return
    fi

    meter_number=0

    while IFS= read -r meter_route; do
        test -z "$meter_route" && continue
        meter_number=$((meter_number + 1))
        validate_route "$meter_route" "mirror-meter-reading-$mup_number-$meter_number"

        reading_route="$meter_route/r?l=2"
        validate_route "$reading_route" "reading-list-$mup_number-$meter_number"
    done <<EOF
$meter_routes
EOF
}

validate_dynamic_telemetry() {
    if ! test -s "$MUP_LIST_FILE"; then
        fail "No existe MirrorUsagePointList para extraer rutas dinámicas"
        return
    fi

    mup_routes=$(extract_routes "$MUP_LIST_FILE" "MirrorUsagePoint")

    if test -z "$mup_routes"; then
        pass "MirrorUsagePointList no contiene puntos de medición"
        return
    fi

    mup_number=0

    while IFS= read -r mup_route; do
        test -z "$mup_route" && continue
        mup_number=$((mup_number + 1))
        validate_route "$mup_route" "mirror-usage-point-$mup_number"
        validate_meter_readings "$mup_route" "$mup_number"
    done <<EOF
$mup_routes
EOF
}

echo "============================================================"
echo "Validación XSD del Mock Server IEEE 2030.5"
echo "============================================================"

mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT_DIR"/*.xml "$OUTPUT_DIR"/*.log

for required_file in "$SERVER_CA" "$CLIENT_CERT_DER" "$CLIENT_KEY" "$SCHEMA"; do
    if test -f "$required_file"; then
        pass "Existe $required_file"
    else
        fail "No existe $required_file"
        exit 1
    fi
done

if ! ss -lnt | grep -q ':8443 '; then
    fail "El servidor no está escuchando en el puerto 8443"
    echo "Inicie el servidor en otra terminal:"
    echo "  cd $PROJECT_DIR"
    echo "  source venv/bin/activate"
    echo "  python3 -m mock_server.app"
    exit 1
fi

pass "El servidor está escuchando en el puerto 8443"

if openssl x509 -inform DER -in "$CLIENT_CERT_DER" -out "$CLIENT_CERT_PEM"; then
    pass "Certificado cliente convertido de DER a PEM"
else
    fail "No fue posible convertir el certificado cliente"
    exit 1
fi

validate_route "/dcap" "dcap"
validate_route "/tm" "time"
validate_route "/edev" "end-device-list"
validate_route "/edev/1" "end-device"
validate_route "/edev/1/rg" "registration"
validate_route "/edev/1/der" "der-list"
validate_route "/edev/1/der/1" "der"
validate_route "/edev/1/der/1/dera" "der-availability"
validate_route "/edev/1/der/1/dercap" "der-capability"
validate_route "/edev/1/der/1/derg" "der-settings"
validate_route "/edev/1/der/1/ders" "der-status"
validate_route "/edev/1/fsa" "fsa-list"
validate_route "/edev/1/fsa/1" "fsa"
validate_route "/edev/1/fsa/1/derp" "der-program-list"
validate_route "/edev/1/fsa/1/derp/1" "der-program"
validate_route "/edev/1/fsa/1/derp/1/dderc" "default-der-control"
validate_route "/edev/1/fsa/1/derp/1/derc" "der-control-list"
validate_dynamic_controls

validate_route "/rsps" "response-set-list"
validate_route "/rsps/1" "response-set"
validate_route "/rsps/1/rsp" "response-list"

validate_route "/mup" "mirror-usage-point-list"
validate_dynamic_telemetry

echo
echo "============================================================"
echo "Resultado"
echo "============================================================"
echo "Pruebas correctas: $PASS_COUNT"
echo "Pruebas fallidas:  $FAIL_COUNT"
echo "Pruebas omitidas:  $SKIP_COUNT"
echo "XML guardados en:  $OUTPUT_DIR"

if test "$FAIL_COUNT" -eq 0; then
    echo
    echo "VALIDACIÓN XSD CORRECTA"
    exit 0
fi

echo
echo "VALIDACIÓN XSD CON ERRORES"
exit 1
