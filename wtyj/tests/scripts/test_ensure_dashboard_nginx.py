import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "ensure_dashboard_nginx.py"
SPEC = importlib.util.spec_from_file_location("ensure_dashboard_nginx", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_tenant_header_is_emitted_once_even_when_upstream_sets_it():
    original = """location /api/ali/ {
    proxy_pass http://tenant;
    add_header X-Unboks-Tenant "ali" always;
}
"""

    updated = MODULE.ensure_single_tenant_header(original)

    assert updated.count("proxy_hide_header X-Unboks-Tenant;") == 1
    assert updated.count("add_header X-Unboks-Tenant") == 1
    assert MODULE.ensure_single_tenant_header(updated) == updated


def test_dashboard_html_is_no_store_but_hashed_assets_keep_their_cache():
    original = """server {
    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~* \\.js$ {
        expires 7d;
        add_header Cache-Control "public, max-age=604800";
    }
}
"""

    updated = MODULE.ensure_dashboard_shell_no_store(original)

    assert "location = /index.html" in updated
    assert 'Cache-Control "no-store, no-cache, must-revalidate, max-age=0"' in updated
    assert 'Cache-Control "public, max-age=604800"' in updated
    assert MODULE.ensure_dashboard_shell_no_store(updated) == updated


def test_unknown_dashboard_shape_fails_closed():
    with pytest.raises(ValueError, match="was not recognized"):
        MODULE.ensure_dashboard_shell_no_store("server { return 200; }\n")
