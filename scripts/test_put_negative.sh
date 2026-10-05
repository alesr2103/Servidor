#!/usr/bin/env bash

set -u
set -o pipefail

PROJECT_DIR="$HOME/Servidor"
CLIENT_DIR="$HOME/Cliente-2030.5"
DATABASE="$PROJECT_DIR/data/server.db"
SERVER_URL="https://127.0.0.1:8443"
SERVER_CA="$PROJECT_DIR/certificados/lab-ca.crt"
CLIENT_CERT_DER="$CLIENT_DIR/pti_dev.x509"
CLIENT_CERT_PEM="/tmp/pti_dev-negative-tests.crt"
CLIENT_KEY="$CLIENT_DIR/pti_dev.pem"
TEMP_DIR="/tmp/ieee20305-put-negative"

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

request() {
    method="$1"
    route="$2"
    content_type="$3"
    body_file="$4"

    curl --silent --show-error \
        --output "$TEMP_DIR/response.txt" \
        --write-out '%{http_code}' \
        --request "$method" \
        --cacert "$SERVER_CA" \
        --cert "$CLIENT_CERT_PEM" \
        --key "$CLIENT_KEY" \
        --header "Content-Type: $content_type" \
        --data-binary "@$body_file" \
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

resource_hashes() {
    sqlite3 -separator '|' "$DATABASE" "
    SELECT resource_type || '|' || lower(hex(xml_body))
    FROM der_resources
    WHERE device_id = 1
    ORDER BY resource_type;
    "
}

echo "============================================================"
echo "Pruebas negativas PUT IEEE 2030.5"
echo "============================================================"

mkdir -p "$TEMP_DIR"
rm -f "$TEMP_DIR"/*

for required_file in "$DATABASE" "$SERVER_CA" "$CLIENT_CERT_DER" "$CLIENT_KEY"; do
    if test -f "$required_file"; then
        pass "Existe $required_file"
    else
        fail "No existe $required_file"
        exit 1
    fi
done

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

BEFORE_HASHES=$(resource_hashes)

cat > "$TEMP_DIR/invalid-dera.xml" <<'EOF'
<DERAvailability xmlns="http://ieee.org/2030.5"/>
EOF

cat > "$TEMP_DIR/invalid-dercap.xml" <<'EOF'
<DERCapability xmlns="http://ieee.org/2030.5"/>
EOF

cat > "$TEMP_DIR/invalid-derg.xml" <<'EOF'
<DERSettings xmlns="http://ieee.org/2030.5"/>
EOF

cat > "$TEMP_DIR/invalid-ders.xml" <<'EOF'
<DERStatus xmlns="http://ieee.org/2030.5"/>
EOF

code=$(request PUT "/edev/1/der/1/dera" "application/sep+xml" "$TEMP_DIR/invalid-dera.xml")
expect_status "DERAvailability inválido según XSD" 400 "$code"

code=$(request PUT "/edev/1/der/1/dercap" "application/sep+xml" "$TEMP_DIR/invalid-dercap.xml")
expect_status "DERCapability inválido según XSD" 400 "$code"

code=$(request PUT "/edev/1/der/1/derg" "application/sep+xml" "$TEMP_DIR/invalid-derg.xml")
expect_status "DERSettings inválido según XSD" 400 "$code"

code=$(request PUT "/edev/1/der/1/ders" "application/sep+xml" "$TEMP_DIR/invalid-ders.xml")
expect_status "DERStatus inválido según XSD" 400 "$code"

cat > "$TEMP_DIR/wrong-root.xml" <<'EOF'
<Time xmlns="http://ieee.org/2030.5">
  <currentTime>1700000000</currentTime>
  <dstEndTime>0</dstEndTime>
  <dstOffset>0</dstOffset>
  <dstStartTime>0</dstStartTime>
  <localTime>0</localTime>
  <quality>3</quality>
  <tzOffset>-21600</tzOffset>
</Time>
EOF

code=$(request PUT "/edev/1/der/1/ders" "application/sep+xml" "$TEMP_DIR/wrong-root.xml")
expect_status "Elemento raíz incorrecto" 400 "$code"

printf '<DERStatus xmlns="http://ieee.org/2030.5">' > "$TEMP_DIR/malformed.xml"

code=$(request PUT "/edev/1/der/1/ders" "application/sep+xml" "$TEMP_DIR/malformed.xml")
expect_status "XML mal formado" 400 "$code"

printf '{"readingTime":1700000000}' > "$TEMP_DIR/body.json"

code=$(request PUT "/edev/1/der/1/ders" "application/json" "$TEMP_DIR/body.json")
expect_status "Content-Type application/json" 415 "$code"

cat > "$TEMP_DIR/valid-ders.xml" <<'EOF'
<DERStatus xmlns="http://ieee.org/2030.5">
  <readingTime>1700000000</readingTime>
</DERStatus>
EOF

code=$(request PUT "/edev/2/der/1/ders" "application/sep+xml" "$TEMP_DIR/valid-ders.xml")
expect_status "Acceso a Device ID ajeno" 403 "$code"

python3 - <<'PY'
from pathlib import Path

path = Path("/tmp/ieee20305-put-negative/oversized.xml")
path.write_bytes(
    b'<DERStatus xmlns="http://ieee.org/2030.5">'
    + b'A' * (1024 * 1024 + 1)
    + b'</DERStatus>'
)
PY

code=$(request PUT "/edev/1/der/1/ders" "application/sep+xml" "$TEMP_DIR/oversized.xml")
expect_status "Cuerpo mayor al límite permitido" 413 "$code"

printf '<DERStatus xmlns="urn:incorrect"><readingTime>1700000000</readingTime></DERStatus>' > "$TEMP_DIR/wrong-namespace.xml"

code=$(request PUT "/edev/1/der/1/ders" "application/sep+xml" "$TEMP_DIR/wrong-namespace.xml")
expect_status "Namespace incorrecto" 400 "$code"

AFTER_HASHES=$(resource_hashes)

if test "$BEFORE_HASHES" = "$AFTER_HASHES"; then
    pass "Los PUT rechazados no modificaron der_resources"
else
    fail "Los PUT rechazados modificaron der_resources"
    printf '%s\n' "--- Antes ---" "$BEFORE_HASHES" "--- Después ---" "$AFTER_HASHES"
fi

echo
echo "============================================================"
echo "Resultado"
echo "============================================================"
echo "Pruebas correctas: $PASS_COUNT"
echo "Pruebas fallidas:  $FAIL_COUNT"

if test "$FAIL_COUNT" -eq 0; then
    echo
    echo "PRUEBAS NEGATIVAS CORRECTAS"
    exit 0
fi

echo
echo "PRUEBAS NEGATIVAS CON ERRORES"
exit 1
