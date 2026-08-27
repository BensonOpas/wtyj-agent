#!/usr/bin/env python3
"""Apply the dashboard proxy invariants required by the browser client."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


TENANT_HEADER = "X-Unboks-Tenant"
DASHBOARD_CACHE_MARKER = "UNBOKS DASHBOARD APP SHELL CACHE POLICY"


def ensure_single_tenant_header(text: str) -> str:
    """Hide an upstream tenant header before adding the proxy-owned value."""
    lines = text.splitlines()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"add_header {TENANT_HEADER} "):
            previous = next(
                (candidate.strip() for candidate in reversed(result) if candidate.strip()),
                "",
            )
            if previous != f"proxy_hide_header {TENANT_HEADER};":
                indent = line[: len(line) - len(line.lstrip())]
                result.append(f"{indent}proxy_hide_header {TENANT_HEADER};")
        result.append(line)
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(result) + suffix


def ensure_dashboard_shell_no_store(text: str) -> str:
    """Keep SPA HTML fresh while leaving hashed assets long-cacheable."""
    no_store = (
        'add_header Cache-Control '
        '"no-store, no-cache, must-revalidate, max-age=0" always;'
    )
    if DASHBOARD_CACHE_MARKER in text or (
        "location = /index.html" in text
        and text.count(no_store) >= 2
    ):
        return text
    legacy = """    location / {
        try_files $uri $uri/ /index.html;
    }
"""
    replacement = f"""    # BEGIN {DASHBOARD_CACHE_MARKER}
    # Hashed static assets retain their long-lived policy below.
    location = /index.html {{
        expires -1;
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
        add_header Pragma "no-cache" always;
    }}

    location / {{
        expires -1;
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
        add_header Pragma "no-cache" always;
        try_files $uri $uri/ /index.html;
    }}
    # END {DASHBOARD_CACHE_MARKER}
"""
    if legacy not in text:
        raise ValueError("dashboard SPA location block was not recognized")
    return text.replace(legacy, replacement, 1)


def atomic_write(path: Path, content: str) -> bool:
    current = path.read_text()
    if current == content:
        return False
    temporary = path.with_name(f".{path.name}.codex-tmp")
    temporary.write_text(content)
    os.chmod(temporary, path.stat().st_mode & 0o777)
    os.replace(temporary, path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-config", required=True, type=Path)
    parser.add_argument("--dashboard-config", required=True, type=Path)
    args = parser.parse_args()

    api_text = args.api_config.read_text()
    dashboard_text = args.dashboard_config.read_text()
    changed = {
        "api": atomic_write(
            args.api_config,
            ensure_single_tenant_header(api_text),
        ),
        "dashboard": atomic_write(
            args.dashboard_config,
            ensure_dashboard_shell_no_store(dashboard_text),
        ),
    }
    print(changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
