#!/usr/bin/env bash
# Public, read-only smoke checks for the canonical api.unboks.org tenant routes.
# Set all three *_DASHBOARD_PASSWORD variables to add authenticated profile and
# cross-tenant token checks. No credential is embedded in this script.
set -euo pipefail

DOMAIN="${UNBOKS_API_BASE_URL:-https://api.unboks.org}"
DOMAIN="${DOMAIN%/}"
SCRATCH_DIR=$(mktemp -d)
trap 'rm -rf "$SCRATCH_DIR"' EXIT

check_health() {
  slug="$1"
  label="$2"
  headers="$SCRATCH_DIR/$slug.headers"
  body="$SCRATCH_DIR/$slug.body"
  status=$(curl -sS --retry 2 --max-time 15 \
    -D "$headers" -o "$body" -w '%{http_code}' \
    "$DOMAIN/api/$slug/health")
  if [ "$status" != "200" ]; then
    echo "FAIL: $label health returned HTTP $status"
    exit 1
  fi
  python3 - "$headers" "$body" "$slug" <<'PY'
import json
import sys

headers_path, body_path, slug = sys.argv[1:]
with open(headers_path, encoding="utf-8") as stream:
    tenant_headers = [
        line.split(":", 1)[1].strip()
        for line in stream
        if line.lower().startswith("x-unboks-tenant:")
    ]
with open(body_path, encoding="utf-8") as stream:
    body = json.load(stream)
if tenant_headers != [slug]:
    raise SystemExit(
        f"FAIL: {slug} tenant headers were {tenant_headers!r}, expected {[slug]!r}"
    )
if body.get("status") != "ok":
    raise SystemExit(f"FAIL: {slug} health body was not ok")
PY
  echo "PASS: $label health and tenant header"
}

echo "[1/6] Mermaid tenant health"
check_health "mermaid" "Mermaid"

echo "[2/6] Ali Car Rental tenant health"
check_health "ali-car-rental" "Ali Car Rental"

echo "[3/6] Consulta Despertares tenant health"
check_health "consulta-despertares" "Consulta Despertares"

echo "[4/6] Unboks tenant health"
check_health "unboks" "Unboks"

echo "[5/6] Unknown tenant rejection"
unknown_slug="not-a-real-tenant"
unknown_headers="$SCRATCH_DIR/unknown.headers"
unknown_status=$(curl -sS --retry 2 --max-time 15 \
  -D "$unknown_headers" -o /dev/null -w '%{http_code}' \
  "$DOMAIN/api/$unknown_slug/health")
if [ "$unknown_status" != "404" ]; then
  echo "FAIL: unknown tenant returned HTTP $unknown_status, expected 404"
  exit 1
fi
if tr -d '\r' < "$unknown_headers" | grep -qi '^X-Unboks-Tenant:'; then
  echo "FAIL: unknown tenant response carried a tenant identity header"
  exit 1
fi
echo "PASS: unknown tenant returned 404 without a tenant identity header"

echo "[6/6] Optional authenticated tenant isolation"
password_count=0
for variable in \
  MERMAID_DASHBOARD_PASSWORD \
  ALI_CAR_RENTAL_DASHBOARD_PASSWORD \
  UNBOKS_DASHBOARD_PASSWORD
do
  if [ -n "${!variable:-}" ]; then
    password_count=$((password_count + 1))
  fi
done

if [ "$password_count" = "0" ]; then
  echo "SKIP: set all three tenant dashboard password variables to run auth checks"
elif [ "$password_count" != "3" ]; then
  echo "FAIL: authenticated isolation requires all three dashboard password variables"
  exit 1
else
  python3 - "$DOMAIN" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

domain = sys.argv[1]
origin = "https://dashboard.unboks.org"
passwords = {
    "mermaid": os.environ["MERMAID_DASHBOARD_PASSWORD"],
    "ali-car-rental": os.environ["ALI_CAR_RENTAL_DASHBOARD_PASSWORD"],
    "unboks": os.environ["UNBOKS_DASHBOARD_PASSWORD"],
}


def request(path, *, method="GET", token="", payload=None):
    headers = {"Accept": "application/json", "Origin": origin}
    data = None
    if token:
        headers["Authorization"] = "Bearer " + token
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()
    req = urllib.request.Request(
        domain + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        response = urllib.request.urlopen(req, timeout=15)
    except urllib.error.HTTPError as exc:
        response = exc
    raw = response.read()
    body = None
    if raw:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            pass
    return response.status, response.headers, body


tokens = {}
for slug, password in passwords.items():
    status, headers, body = request(
        f"/api/{slug}/dashboard/api/login",
        method="POST",
        payload={"password": password},
    )
    if status != 200 or headers.get_all("X-Unboks-Tenant") != [slug]:
        raise SystemExit(f"FAIL: {slug} authenticated login isolation")
    if not isinstance(body, dict) or not body.get("token"):
        raise SystemExit(f"FAIL: {slug} login returned no token")
    tokens[slug] = body["token"]

    status, headers, body = request(
        f"/api/{slug}/dashboard/api/client/profile",
        token=tokens[slug],
    )
    if status != 200 or headers.get_all("X-Unboks-Tenant") != [slug]:
        raise SystemExit(f"FAIL: {slug} authenticated profile isolation")
    if not isinstance(body, dict) or body.get("slug") != slug:
        raise SystemExit(f"FAIL: {slug} profile payload identity")

for source, target in (
    ("mermaid", "ali-car-rental"),
    ("ali-car-rental", "mermaid"),
    ("mermaid", "unboks"),
    ("unboks", "mermaid"),
):
    status, headers, _ = request(
        f"/api/{target}/dashboard/api/client/profile",
        token=tokens[source],
    )
    if status not in {401, 403}:
        raise SystemExit(f"FAIL: {source} token reached {target}: HTTP {status}")
    if headers.get_all("X-Unboks-Tenant") != [target]:
        raise SystemExit(f"FAIL: {target} rejection carried the wrong tenant header")

status, headers, _ = request(
    "/api/not-a-real-tenant/dashboard/api/client/profile",
    token=tokens["unboks"],
)
if status != 404 or headers.get_all("X-Unboks-Tenant"):
    raise SystemExit("FAIL: authenticated unknown tenant route was not rejected")
print("PASS: authenticated profiles, token isolation, and unknown route")
PY
fi

echo "Public tenant smoke checks passed against $DOMAIN"
