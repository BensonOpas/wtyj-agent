#!/usr/bin/env bash
# Brief 200 — smoke tests for api.unboks.org cutover.
# Run AFTER DNS is flipped and certbot has issued the TLS cert.
# Exits non-zero on any failure.
set -e

DOMAIN="https://api.unboks.org"

echo "[1/6] Health (root /api/healthz)..."
RESULT=$(curl -s -o /dev/null -w '%{http_code}' "$DOMAIN/api/healthz")
[ "$RESULT" = "200" ] || { echo "FAIL: healthz returned $RESULT"; exit 1; }

echo "[2/6] BlueMarlin tenant health..."
RESULT=$(curl -s -o /dev/null -w '%{http_code}' "$DOMAIN/api/bluemarlin/health")
[ "$RESULT" = "200" ] || { echo "FAIL: bluemarlin health $RESULT"; exit 1; }

echo "[3/6] Adamus tenant health..."
RESULT=$(curl -s -o /dev/null -w '%{http_code}' "$DOMAIN/api/adamus/health")
[ "$RESULT" = "200" ] || { echo "FAIL: adamus health $RESULT"; exit 1; }

echo "[4/6] Unboks tenant health..."
RESULT=$(curl -s -o /dev/null -w '%{http_code}' "$DOMAIN/api/unboks/health")
[ "$RESULT" = "200" ] || { echo "FAIL: unboks health $RESULT"; exit 1; }

echo "[5/6] Unboks login returns JWT (using DASHBOARD_PASSWORD=papaesunmono)..."
TOKEN=$(curl -s -X POST "$DOMAIN/api/unboks/dashboard/api/login" \
  -H "Content-Type: application/json" \
  -d '{"password":"papaesunmono"}' | python3 -c 'import sys, json; d = json.load(sys.stdin); print(d.get("token",""))')
[ -n "$TOKEN" ] || { echo "FAIL: login did not return token"; exit 1; }

echo "[6/6] Unboks conversations endpoint via JWT..."
RESULT=$(curl -s -o /dev/null -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" \
  "$DOMAIN/api/unboks/dashboard/api/messages/conversations")
[ "$RESULT" = "200" ] || { echo "FAIL: conversations endpoint $RESULT"; exit 1; }

echo ""
echo "All 6 smoke checks passed against $DOMAIN"
