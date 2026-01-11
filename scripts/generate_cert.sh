#!/bin/bash
# Generate self-signed SSL certificate for local HTTPS development
# Usage: ./scripts/generate_cert.sh [domain]

set -e

DOMAIN="${1:-localhost}"
CERT_DIR="certs"

# Create certs directory if it doesn't exist
mkdir -p "$CERT_DIR"

echo "Generating self-signed certificate for: $DOMAIN"

# Generate private key and self-signed certificate
openssl req -x509 -newkey rsa:4096 \
    -keyout "$CERT_DIR/key.pem" \
    -out "$CERT_DIR/cert.pem" \
    -days 365 \
    -nodes \
    -subj "/CN=$DOMAIN" \
    -addext "subjectAltName=DNS:$DOMAIN,DNS:localhost,IP:127.0.0.1"

echo ""
echo "Certificate generated successfully!"
echo "  Certificate: $CERT_DIR/cert.pem"
echo "  Private key: $CERT_DIR/key.pem"
echo ""
echo "To start the server with HTTPS:"
echo "  just dev-https"
echo ""
echo "Note: Browsers will show a warning for self-signed certificates."
echo "You'll need to accept the certificate to proceed."
