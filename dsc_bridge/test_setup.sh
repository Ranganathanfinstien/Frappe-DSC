#!/bin/bash
# ============================================================
# SoftHSM2 Test Setup for dsc-bridge
# ============================================================
# This script sets up a SoftHSM2 token with a test key pair
# and self-signed certificate for local development/testing.
#
# Prerequisites:
#   sudo apt install softhsm2 opensc openssl
#
# Usage:
#   chmod +x test_setup.sh
#   ./test_setup.sh
# ============================================================

set -e

SOFTHSM_LIB="/usr/lib/softhsm/libsofthsm2.so"
TOKEN_LABEL="TestDSC"
PIN="1234"
SO_PIN="5678"
KEY_ID="01"
KEY_LABEL="TestKey"
CERT_LABEL="TestCert"
WORK_DIR=$(mktemp -d)

echo "=== SoftHSM2 Test Setup ==="
echo ""

# Step 1: Check prerequisites
echo "[1/6] Checking prerequisites..."
for cmd in softhsm2-util pkcs11-tool openssl; do
    if ! command -v $cmd &> /dev/null; then
        echo "ERROR: $cmd not found. Install with:"
        echo "  sudo apt install softhsm2 opensc openssl"
        exit 1
    fi
done

if [ ! -f "$SOFTHSM_LIB" ]; then
    echo "ERROR: SoftHSM2 library not found at $SOFTHSM_LIB"
    exit 1
fi
echo "  All prerequisites found."

# Step 2: Initialize token (delete existing if present)
echo "[2/6] Initializing SoftHSM2 token..."
softhsm2-util --delete-token --token "$TOKEN_LABEL" 2>/dev/null || true

SLOT=$(softhsm2-util --init-token --free --label "$TOKEN_LABEL" --pin "$PIN" --so-pin "$SO_PIN" 2>&1 | grep -oP 'reassigned to \K\d+' || echo "0")
echo "  Token '$TOKEN_LABEL' initialized on slot $SLOT"

# Step 3: Generate RSA 2048 key pair on the token
echo "[3/6] Generating RSA 2048 key pair on token..."
pkcs11-tool --module "$SOFTHSM_LIB" \
    --login --pin "$PIN" \
    --keypairgen --key-type rsa:2048 \
    --id "$KEY_ID" --label "$KEY_LABEL"
echo "  Key pair generated."

# Step 4: Create a self-signed certificate
echo "[4/6] Creating self-signed test certificate..."
cat > "$WORK_DIR/cert.conf" << EOF
[req]
distinguished_name = req_dn
x509_extensions = v3_ext
prompt = no

[req_dn]
CN = RANGA TEST SIGNER
O = DSC Bridge Test
C = IN

[v3_ext]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, nonRepudiation
extendedKeyUsage = emailProtection
subjectKeyIdentifier = hash
authorityInfoAccess = OCSP;URI:http://ocsp.test.local
EOF

# Export public key from token
pkcs11-tool --module "$SOFTHSM_LIB" \
    --login --pin "$PIN" \
    --read-object --type pubkey --id "$KEY_ID" \
    --output-file "$WORK_DIR/pubkey.der"

# Convert DER public key to PEM
openssl rsa -pubin -inform DER -in "$WORK_DIR/pubkey.der" -outform PEM -out "$WORK_DIR/pubkey.pem"

# Generate a temporary private key for cert signing (not the token key)
openssl genrsa -out "$WORK_DIR/tmp_key.pem" 2048

# Create self-signed cert
openssl req -new -x509 -days 365 \
    -config "$WORK_DIR/cert.conf" \
    -key "$WORK_DIR/tmp_key.pem" \
    -out "$WORK_DIR/cert.pem"

# Convert to DER
openssl x509 -in "$WORK_DIR/cert.pem" -outform DER -out "$WORK_DIR/cert.der"

echo "  Certificate created."

# Step 5: Import certificate onto the token
echo "[5/6] Importing certificate onto token..."
pkcs11-tool --module "$SOFTHSM_LIB" \
    --login --pin "$PIN" \
    --write-object "$WORK_DIR/cert.der" \
    --type cert --id "$KEY_ID" --label "$CERT_LABEL"
echo "  Certificate imported."

# Step 6: Verify
echo "[6/6] Verifying token contents..."
echo ""
echo "--- Token Objects ---"
pkcs11-tool --module "$SOFTHSM_LIB" --login --pin "$PIN" --list-objects
echo ""

# Print cert fingerprint
FINGERPRINT=$(openssl x509 -in "$WORK_DIR/cert.pem" -noout -fingerprint -sha256 | sed 's/.*=//;s/://g' | tr 'A-F' 'a-f')
echo "--- Test Certificate ---"
echo "  Subject:     RANGA TEST SIGNER, O=DSC Bridge Test, C=IN"
echo "  Fingerprint: $FINGERPRINT"
echo "  PIN:         $PIN"
echo ""

# Cleanup temp files
rm -rf "$WORK_DIR"

echo "=== Setup Complete ==="
echo ""
echo "To test dsc-bridge, create a config file:"
echo ""
echo "  mkdir -p ~/.local/share/dsc-bridge"
echo "  cat > ~/.local/share/dsc-bridge/dsc-bridge.json << EOF"
echo "  {"
echo "    \"pkcs11_libs\": [\"$SOFTHSM_LIB\"]"
echo "  }"
echo "  EOF"
echo ""
echo "Then run: ./dsc-bridge"
echo "And test: curl -k https://127.0.0.1:4645/v1/status"
