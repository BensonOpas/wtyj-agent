import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlsplit

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "smoke_unboks_domain.sh"
KNOWN = {"mermaid", "ali-car-rental", "consulta-despertares", "unboks"}
PASSWORDS = {slug: f"password-{slug}" for slug in KNOWN}
PASSWORD_ENV = {
    "mermaid": "MERMAID_DASHBOARD_PASSWORD",
    "ali-car-rental": "ALI_CAR_RENTAL_DASHBOARD_PASSWORD",
    "unboks": "UNBOKS_DASHBOARD_PASSWORD",
}


def _handler(*, unsafe_unknown: bool = False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _send(self, status, body=None, tenant=None):
            raw = json.dumps(body).encode() if body is not None else b""
            self.send_response(status)
            if tenant:
                self.send_header("X-Unboks-Tenant", tenant)
            if raw:
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            if raw:
                self.wfile.write(raw)

        def do_GET(self):
            parts = urlsplit(self.path).path.strip("/").split("/")
            slug = parts[1] if len(parts) > 1 and parts[0] == "api" else ""
            if slug not in KNOWN:
                if unsafe_unknown and parts[-1] == "health":
                    self._send(200, {"status": "ok"}, slug)
                else:
                    self._send(404)
                return
            if parts[2:] == ["health"]:
                self._send(200, {"status": "ok"}, slug)
                return
            if parts[2:] == ["dashboard", "api", "client", "profile"]:
                if self.headers.get("Authorization") != f"Bearer token-{slug}":
                    self._send(401, {"detail": "Missing or invalid token"}, slug)
                    return
                self._send(200, {"slug": slug, "name": slug}, slug)
                return
            self._send(404, tenant=slug)

        def do_POST(self):
            parts = urlsplit(self.path).path.strip("/").split("/")
            slug = parts[1] if len(parts) > 1 and parts[0] == "api" else ""
            if slug not in KNOWN:
                self._send(404)
                return
            if parts[2:] != ["dashboard", "api", "login"]:
                self._send(404, tenant=slug)
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            if body.get("password") != PASSWORDS[slug]:
                self._send(401, {"detail": "Wrong password"}, slug)
                return
            self._send(200, {"token": f"token-{slug}"}, slug)

    return Handler


@pytest.fixture
def api_server(request):
    unsafe_unknown = bool(getattr(request, "param", False))
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(unsafe_unknown=unsafe_unknown))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _run_smoke(base_url, *, authenticated=False):
    env = os.environ.copy()
    env["UNBOKS_API_BASE_URL"] = base_url
    for variable in PASSWORD_ENV.values():
        env.pop(variable, None)
    if authenticated:
        for slug, variable in PASSWORD_ENV.items():
            env[variable] = PASSWORDS[slug]
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_script_has_valid_shell_syntax_and_no_embedded_password():
    syntax = subprocess.run(
        ["bash", "-n", str(SCRIPT)],
        text=True,
        capture_output=True,
        check=False,
    )
    contents = SCRIPT.read_text()

    assert syntax.returncode == 0, syntax.stderr
    assert "/api/healthz" not in contents
    assert "using DASHBOARD_PASSWORD=" not in contents
    assert "not-a-real-tenant" in contents
    assert "UNBOKS_DASHBOARD_PASSWORD" in contents


def test_public_smoke_accepts_explicit_routes_and_unknown_404(api_server):
    result = _run_smoke(api_server)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: unknown tenant returned 404" in result.stdout
    assert "SKIP: set all three" in result.stdout


def test_authenticated_smoke_checks_profiles_and_cross_tenant_tokens(api_server):
    result = _run_smoke(api_server, authenticated=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: authenticated profiles, token isolation, and unknown route" in result.stdout


@pytest.mark.parametrize("api_server", [True], indirect=True)
def test_public_smoke_rejects_legacy_unknown_tenant_alias(api_server):
    result = _run_smoke(api_server)

    assert result.returncode != 0
    assert "unknown tenant returned HTTP 200, expected 404" in result.stdout
