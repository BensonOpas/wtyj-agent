#!/usr/bin/env bash
# Brief 200 — cutover script for api.unboks.org TLS issuance.
# Prerequisite: DNS A record for api.unboks.org points at 108.61.192.52.
# Run on VPS as root: bash wtyj/scripts/cutover_unboks_domain.sh
set -e

DOMAIN="api.unboks.org"

echo "[1/4] Verifying DNS resolves to this VPS..."
RESOLVED=$(dig +short "$DOMAIN" | tail -1)
EXPECTED="108.61.192.52"
if [ "$RESOLVED" != "$EXPECTED" ]; then
    echo "FAIL: $DOMAIN resolves to '$RESOLVED', expected '$EXPECTED'"
    echo "Has SR's DNS change propagated? Try again in a few minutes."
    exit 1
fi
echo "  -> $DOMAIN -> $RESOLVED OK"

echo "[2/4] Running certbot to issue TLS cert..."
certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos \
    --email butlerbensonagent@gmail.com --redirect

echo "[3/4] Validating nginx config..."
nginx -t

echo "[4/4] Reloading nginx..."
systemctl reload nginx

echo ""
echo "Cutover complete. Verify externally:"
echo "  curl -s https://$DOMAIN/api/healthz"
