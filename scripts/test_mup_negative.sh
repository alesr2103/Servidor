#!/usr/bin/env bash

set -u
set -o pipefail

PROJECT_DIR="$HOME/Servidor"
CLIENT_DIR="$HOME/Cliente-2030.5"
SERVER_URL="https://127.0.0.1:8443"
DATABASE="$PROJECT_DIR/data/server.db"
SERVER_CA="$PROJECT_DIR/certificados/lab-ca.crt"
CLIENT_CERT_DER="$CLIENT_DIR/pti_dev.x509"
CLIENT_CERT_PEM="/tmp/pti_dev-mup-negative.crt"
CLIENT_KEY="$CLIENT_DIR/pti_dev.pem"
TMP_DIR="/tmp/ieee20305-mup-negative"
CONTENT_TYPE="application/sep+xml"
LFDI="0671c144d27dc9e612afe7dc6c79ec089ed3dcc5"
WRONG_LFDI="00112233445566778899aabbccddeeff00112233"

PASS_COUNT=0
FAIL_COUNT=0

pass() {
    printf '[OK] %s\n' "$1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
    printf '[ERROR] %s\n' "$1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

require_file() {
    if test -f "$1"; then
        pass "Existe $1"
    else
        fail "No existe $1"
        exit 1
    fi
}

snapshot_telemetry() {
    output="$1"

    sqlite3 -batch -noheader "$DATABASE" "
    SELECT 'mup|' || id || '|' || device_id || '|' || mrid || '|' ||
           IFNULL(description, '') || '|' || role_flags || '|' ||
           service_category || '|' || post_rate || '|' ||
           IFNULL(device_lfdi, '') || '|' || IFNULL(status, '') || '|' ||
           hex(xml_body) || '|' || created_at || '|' || updated_at
    FROM mirror_usage_points
    ORDER BY id;

    SELECT 'mmr|' || id || '|' || usage_point_id || '|' || mrid || '|' ||
           IFNULL(description, '') || '|' || reading_type || '|' ||
           IFNULL(phase, '') || '|' || IFNULL(uom, '') || '|' ||
           power_of_ten_multiplier || '|' || IFNULL(flow_direction, '') || '|' ||
           IFNULL(accumulation_behaviour, '') || '|' || IFNULL(commodity, '') || '|' ||
           IFNULL(data_qualifier, '') || '|' || IFNULL(kind, '') || '|' ||
           IFNULL(hex(reading_type_xml), '') || '|' || created_at || '|' || updated_at
    FROM mirror_meter_readings
    ORDER BY id;

    SELECT 'reading|' || id || '|' || meter_reading_id || '|' || value || '|' ||
           reading_time || '|' || IFNULL(quality_flags, '') || '|' ||
           hex(xml_body) || '|' || received_at
    FROM meter_readings
    ORDER BY id;
    " | sha256sum | awk '{print $1}' > "$output"
}

post_xml() {
    route="$1"
    input="$2"
    output="$3"

    curl --silent --show-error \
        --output "$output" \
        --write-out '%{http_code}' \
        --cacert "$SERVER_CA" \
        --cert "$CLIENT_CERT_PEM" \
        --key "$CLIENT_KEY" \
        --header "Content-Type: $CONTENT_TYPE" \
        --data-binary "@$input" \
        "$SERVER_URL$route"
}

expect_status() {
    description="$1"
    expected="$2"
    actual="$3"

    if test "$actual" = "$expected"; then
        pass "$description devolvió HTTP $expected"
    else
        fail "$description devolvió HTTP $actual; esperado $expected"
    fi
}

echo "============================================================"
echo "Pruebas negativas de telemetría IEEE 2030.5"
echo "============================================================"

mkdir -p "$TMP_DIR"
rm -f "$TMP_DIR"/*

require_file "$DATABASE"
require_file "$SERVER_CA"
require_file "$CLIENT_CERT_DER"
require_file "$CLIENT_KEY"

if ss -lnt | grep -q ':8443 '; then
    pass "El servidor escucha en el puerto 8443"
else
    fail "El servidor no escucha en el puerto 8443"
    exit 1
fi

if openssl x509 -inform DER -in "$CLIENT_CERT_DER" -out "$CLIENT_CERT_PEM"; then
    pass "Certificado cliente convertido a PEM"
else
    fail "No fue posible convertir el certificado cliente"
    exit 1
fi

MUP_ID=$(sqlite3 "$DATABASE" "SELECT id FROM mirror_usage_points ORDER BY id LIMIT 1;")
METER_MRID=$(sqlite3 "$DATABASE" "SELECT mrid FROM mirror_meter_readings WHERE usage_point_id=$MUP_ID ORDER BY id LIMIT 1;")

if test -z "$MUP_ID" || test -z "$METER_MRID"; then
    fail "No existen datos de telemetría para ejecutar las pruebas"
    exit 1
fi

pass "Datos de referencia encontrados: mup_id=$MUP_ID"

snapshot_telemetry "$TMP_DIR/before.sha256"

cat > "$TMP_DIR/mup-xsd-invalid.xml" <<XML
<MirrorUsagePoint xmlns="http://ieee.org/2030.5">
  <mRID>AA0000000000000000000001</mRID>
</MirrorUsagePoint>
XML

HTTP_CODE=$(post_xml "/mup" "$TMP_DIR/mup-xsd-invalid.xml" "$TMP_DIR/mup-xsd-invalid.out")
expect_status "MirrorUsagePoint inválido según XSD" 400 "$HTTP_CODE"

cat > "$TMP_DIR/mmr-xsd-invalid.xml" <<XML
<MirrorMeterReading xmlns="http://ieee.org/2030.5">
  <mRID>BB0000000000000000000001</mRID>
  <ReadingType>
    <uom>300</uom>
  </ReadingType>
</MirrorMeterReading>
XML

HTTP_CODE=$(post_xml "/mup/$MUP_ID" "$TMP_DIR/mmr-xsd-invalid.xml" "$TMP_DIR/mmr-xsd-invalid.out")
expect_status "MirrorMeterReading inválido según XSD" 400 "$HTTP_CODE"

printf '%s\n' '<MirrorUsagePoint xmlns="http://ieee.org/2030.5"><mRID>AA' > "$TMP_DIR/malformed.xml"
HTTP_CODE=$(post_xml "/mup" "$TMP_DIR/malformed.xml" "$TMP_DIR/malformed.out")
expect_status "XML mal formado" 400 "$HTTP_CODE"

cat > "$TMP_DIR/wrong-root.xml" <<XML
<Time xmlns="http://ieee.org/2030.5">
  <currentTime>1790972035</currentTime>
  <dstEndTime>0</dstEndTime>
  <dstOffset>0</dstOffset>
  <dstStartTime>0</dstStartTime>
  <localTime>0</localTime>
  <quality>3</quality>
  <tzOffset>-21600</tzOffset>
</Time>
XML

HTTP_CODE=$(post_xml "/mup" "$TMP_DIR/wrong-root.xml" "$TMP_DIR/wrong-root.out")
expect_status "Elemento raíz incorrecto" 400 "$HTTP_CODE"

cat > "$TMP_DIR/wrong-lfdi.xml" <<XML
<MirrorUsagePoint xmlns="http://ieee.org/2030.5">
  <mRID>AA0000000000000000000002</mRID>
  <roleFlags>09</roleFlags>
  <serviceCategoryKind>0</serviceCategoryKind>
  <status>1</status>
  <deviceLFDI>$WRONG_LFDI</deviceLFDI>
  <postRate>300</postRate>
</MirrorUsagePoint>
XML

HTTP_CODE=$(post_xml "/mup" "$TMP_DIR/wrong-lfdi.xml" "$TMP_DIR/wrong-lfdi.out")
expect_status "deviceLFDI distinto al certificado" 403 "$HTTP_CODE"

cat > "$TMP_DIR/valid-meter.xml" <<XML
<MirrorMeterReading xmlns="http://ieee.org/2030.5">
  <mRID>BB0000000000000000000002</mRID>
  <description>Current test</description>
  <ReadingType>
    <commodity>1</commodity>
    <flowDirection>1</flowDirection>
    <kind>0</kind>
    <powerOfTenMultiplier>0</powerOfTenMultiplier>
    <uom>5</uom>
  </ReadingType>
</MirrorMeterReading>
XML

HTTP_CODE=$(post_xml "/mup/999999" "$TMP_DIR/valid-meter.xml" "$TMP_DIR/missing-mup.out")
expect_status "MirrorUsagePoint inexistente" 404 "$HTTP_CODE"

cat > "$TMP_DIR/reading-missing-start.xml" <<XML
<MirrorMeterReading xmlns="http://ieee.org/2030.5">
  <mRID>$METER_MRID</mRID>
  <Reading>
    <value>20</value>
  </Reading>
</MirrorMeterReading>
XML

HTTP_CODE=$(post_xml "/mup/$MUP_ID" "$TMP_DIR/reading-missing-start.xml" "$TMP_DIR/reading-missing-start.out")
expect_status "Reading sin timePeriod/start" 400 "$HTTP_CODE"

cat > "$TMP_DIR/unknown-meter.xml" <<XML
<MirrorMeterReading xmlns="http://ieee.org/2030.5">
  <mRID>FFFFFFFFFFFFFFFFFFFFFFFF</mRID>
  <Reading>
    <timePeriod>
      <duration>0</duration>
      <start>1790972035</start>
    </timePeriod>
    <value>20</value>
  </Reading>
</MirrorMeterReading>
XML

HTTP_CODE=$(post_xml "/mup/$MUP_ID" "$TMP_DIR/unknown-meter.xml" "$TMP_DIR/unknown-meter.out")
expect_status "Reading con mRID desconocido" 400 "$HTTP_CODE"

printf '%s\n' '{"value":20}' > "$TMP_DIR/body.json"

HTTP_CODE=$(curl --silent --show-error \
    --output "$TMP_DIR/json.out" \
    --write-out '%{http_code}' \
    --cacert "$SERVER_CA" \
    --cert "$CLIENT_CERT_PEM" \
    --key "$CLIENT_KEY" \
    --header 'Content-Type: application/json' \
    --data-binary "@$TMP_DIR/body.json" \
    "$SERVER_URL/mup/$MUP_ID")

expect_status "Content-Type application/json" 415 "$HTTP_CODE"

python3 - "$TMP_DIR/oversized.xml" <<'PY'
import sys

payload = "X" * (2 * 1024 * 1024)
body = (
    '<MirrorMeterReading xmlns="http://ieee.org/2030.5">'
    '<mRID>BB0000000000000000000003</mRID>'
    f'<description>{payload}</description>'
    '</MirrorMeterReading>'
)
with open(sys.argv[1], "w", encoding="utf-8") as output:
    output.write(body)
PY

HTTP_CODE=$(post_xml "/mup/$MUP_ID" "$TMP_DIR/oversized.xml" "$TMP_DIR/oversized.out")
expect_status "Cuerpo mayor al límite permitido" 413 "$HTTP_CODE"

snapshot_telemetry "$TMP_DIR/after.sha256"

if cmp -s "$TMP_DIR/before.sha256" "$TMP_DIR/after.sha256"; then
    pass "Los POST rechazados no modificaron las tablas de telemetría"
else
    fail "Las tablas de telemetría cambiaron durante las pruebas negativas"
    echo "Antes:   $(cat "$TMP_DIR/before.sha256")"
    echo "Después: $(cat "$TMP_DIR/after.sha256")"
fi

echo
echo "============================================================"
echo "Resultado"
echo "============================================================"
echo "Pruebas correctas: $PASS_COUNT"
echo "Pruebas fallidas:  $FAIL_COUNT"
echo "Archivos temporales: $TMP_DIR"

if test "$FAIL_COUNT" -eq 0; then
    echo
    echo "PRUEBAS NEGATIVAS DE TELEMETRÍA CORRECTAS"
    exit 0
fi

echo
echo "PRUEBAS NEGATIVAS DE TELEMETRÍA CON ERRORES"
exit 1
