import importlib.util
import os
from pathlib import Path
import re
import subprocess

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "ensure_dashboard_nginx.py"
WORKFLOW = Path(__file__).parents[3] / ".github" / "workflows" / "deploy-dashboard.yml"
SPEC = importlib.util.spec_from_file_location("ensure_dashboard_nginx", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def api_config() -> str:
    return """server {
    location /api/blue-marlin/ {
        proxy_pass http://blue;
        add_header X-Unboks-Tenant "blue-marlin" always;
    }

    # BEGIN UNBOKS TENANT ali-car-rental
    location ^~ /api/ali-car-rental/ {
        proxy_pass http://ali;
        add_header X-Unboks-Tenant "ali-car-rental" always;
    }
    # END UNBOKS TENANT ali-car-rental

    location /api/unboks/ {
        add_header X-Unboks-Tenant "unboks" always;
        add_header X-Unboks-Tenant "intentionally-untouched" always;
    }
}
"""


def legacy_dashboard_config() -> str:
    return """server {
    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~* \\.js$ {
        expires 7d;
        add_header Cache-Control "public, max-age=604800";
    }
}
"""


def test_tenant_header_change_is_scoped_to_exact_ali_location():
    original = api_config()
    expected = original.replace(
        '        add_header X-Unboks-Tenant "ali-car-rental" always;',
        "        proxy_hide_header X-Unboks-Tenant;\n"
        '        add_header X-Unboks-Tenant "ali-car-rental" always;',
    )

    updated = MODULE.ensure_single_tenant_header(original)

    assert updated == expected
    assert MODULE.ensure_single_tenant_header(updated) == updated


def test_tenant_header_transform_preserves_crlf_outside_inserted_line():
    original = api_config().replace("\n", "\r\n")
    updated = MODULE.ensure_single_tenant_header(original)

    assert updated.replace(
        "        proxy_hide_header X-Unboks-Tenant;\r\n",
        "",
        1,
    ) == original
    assert "\n" not in updated.replace("\r\n", "")


def test_old_ali_location_does_not_match_the_rental_tenant():
    original = api_config().replace("/api/ali-car-rental/", "/api/ali/")

    with pytest.raises(ValueError, match="found 0"):
        MODULE.ensure_single_tenant_header(original)


def test_ali_location_outside_its_markers_fails_closed():
    original = api_config().replace(
        "    # BEGIN UNBOKS TENANT ali-car-rental\n",
        "",
    ).replace(
        "    # END UNBOKS TENANT ali-car-rental\n",
        "    # BEGIN UNBOKS TENANT ali-car-rental\n"
        "    # END UNBOKS TENANT ali-car-rental\n",
    )

    with pytest.raises(ValueError, match="outside its Ali rental tenant markers"):
        MODULE.ensure_single_tenant_header(original)


def test_duplicate_ali_locations_fail_closed():
    location = """    location /api/ali-car-rental/ {
        add_header X-Unboks-Tenant "ali-car-rental" always;
    }
"""

    with pytest.raises(ValueError, match="found 2"):
        MODULE.ensure_single_tenant_header(
            "server {\n"
            "    # BEGIN UNBOKS TENANT ali-car-rental\n"
            f"{location}{location}"
            "    # END UNBOKS TENANT ali-car-rental\n"
            "}\n"
        )


@pytest.mark.parametrize(
    "ali_body, message",
    [
        (
            '        add_header X-Unboks-Tenant "wrong-tenant" always;\n',
            "unexpected X-Unboks-Tenant value",
        ),
        (
            '        add_header X-Unboks-Tenant "ali-car-rental" always;\n'
            '        add_header X-Unboks-Tenant "ali-car-rental" always;\n',
            "exactly one direct add_header",
        ),
        (
            '        proxy_hide_header X-Unboks-Tenant;\n'
            '        proxy_hide_header X-Unboks-Tenant;\n'
            '        add_header X-Unboks-Tenant "ali-car-rental" always;\n',
            "ambiguous proxy_hide_header",
        ),
    ],
)
def test_ambiguous_ali_header_policy_fails_closed(ali_body, message):
    original = f"""server {{
    # BEGIN UNBOKS TENANT ali-car-rental
    location /api/ali-car-rental/ {{
{ali_body}    }}
    # END UNBOKS TENANT ali-car-rental
}}
"""

    with pytest.raises(ValueError, match=message):
        MODULE.ensure_single_tenant_header(original)


def test_dashboard_html_is_no_store_but_hashed_assets_are_byte_identical():
    original = legacy_dashboard_config()
    asset_block = """    location ~* \\.js$ {
        expires 7d;
        add_header Cache-Control "public, max-age=604800";
    }
"""

    updated = MODULE.ensure_dashboard_shell_no_store(original)

    assert "location = /index.html" in updated
    assert updated.count(
        'add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;'
    ) == 2
    assert asset_block in updated
    assert MODULE.ensure_dashboard_shell_no_store(updated) == updated


def test_existing_structurally_equivalent_dashboard_policy_is_idempotent():
    existing = """server {
    location = /index.html {
        expires -1;
        add_header   Cache-Control   'no-store, no-cache, must-revalidate, max-age=0'   always ;
    }
    location / {
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
        try_files   $uri   $uri/   /index.html ;
    }
}
"""

    assert MODULE.ensure_dashboard_shell_no_store(existing) == existing


def test_unrelated_no_store_headers_do_not_fake_app_shell_equivalence():
    incomplete = """server {
    location = /index.html {
        expires -1;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
    location /login {
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
    }
    location /settings {
        add_header Cache-Control "no-store, no-cache, must-revalidate, max-age=0" always;
    }
}
"""

    with pytest.raises(ValueError, match="incomplete or ambiguous"):
        MODULE.ensure_dashboard_shell_no_store(incomplete)


def test_marker_without_complete_structural_policy_fails_closed():
    incomplete = f"""server {{
    # BEGIN {MODULE.DASHBOARD_CACHE_MARKER}
    location / {{
        try_files $uri $uri/ /index.html;
    }}
}}
"""

    with pytest.raises(ValueError, match="marker is incomplete"):
        MODULE.ensure_dashboard_shell_no_store(incomplete)


def test_duplicate_dashboard_locations_fail_closed():
    duplicate = """server {
    location / {
        try_files $uri $uri/ /index.html;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
}
"""

    with pytest.raises(ValueError, match="exactly one legacy root"):
        MODULE.ensure_dashboard_shell_no_store(duplicate)


def test_unknown_dashboard_shape_fails_closed():
    with pytest.raises(ValueError, match="exactly one legacy root"):
        MODULE.ensure_dashboard_shell_no_store("server { return 200; }\n")


def test_atomic_write_preserves_symlink_target_metadata_and_fsyncs_directory(
    tmp_path,
    monkeypatch,
):
    target = tmp_path / "sites-available-api"
    target.write_text("old\n")
    target.chmod(0o640)
    expected_owner = (target.stat().st_uid, target.stat().st_gid)
    link = tmp_path / "sites-enabled-api"
    link.symlink_to(target)
    real_fchown = os.fchown
    ownership_calls = []
    real_fsync_directory = MODULE._fsync_directory
    fsynced_directories = []

    def record_fchown(descriptor, uid, gid):
        ownership_calls.append((uid, gid))
        real_fchown(descriptor, uid, gid)

    def record_directory_fsync(directory):
        fsynced_directories.append(directory)
        real_fsync_directory(directory)

    monkeypatch.setattr(MODULE.os, "fchown", record_fchown)
    monkeypatch.setattr(MODULE, "_fsync_directory", record_directory_fsync)

    assert MODULE.atomic_write(link, "new\n") is True

    assert link.is_symlink()
    assert link.read_text() == "new\n"
    assert target.read_text() == "new\n"
    assert target.stat().st_mode & 0o777 == 0o640
    assert (target.stat().st_uid, target.stat().st_gid) == expected_owner
    assert ownership_calls == [expected_owner, expected_owner]
    assert fsynced_directories == [tmp_path]


def test_transform_failure_writes_neither_config(tmp_path):
    api_path = tmp_path / "api"
    dashboard_path = tmp_path / "dashboard"
    api_original = api_config()
    dashboard_original = "server { return 200; }\n"
    api_path.write_text(api_original)
    dashboard_path.write_text(dashboard_original)

    with pytest.raises(ValueError):
        MODULE.apply_config_updates(api_path, dashboard_path)

    assert api_path.read_text() == api_original
    assert dashboard_path.read_text() == dashboard_original


def test_second_write_failure_rolls_back_first_config(tmp_path, monkeypatch):
    api_path = tmp_path / "api"
    dashboard_path = tmp_path / "dashboard"
    api_original = api_config()
    dashboard_original = legacy_dashboard_config()
    api_path.write_text(api_original)
    dashboard_path.write_text(dashboard_original)
    real_replace = os.replace
    activations = 0

    def fail_second_activation(source, destination):
        nonlocal activations
        if ".new." in Path(source).name:
            activations += 1
            if activations == 2:
                raise OSError("simulated second activation failure")
        return real_replace(source, destination)

    monkeypatch.setattr(MODULE.os, "replace", fail_second_activation)

    with pytest.raises(OSError, match="second activation failure"):
        MODULE.apply_config_updates(api_path, dashboard_path)

    assert api_path.read_text() == api_original
    assert dashboard_path.read_text() == dashboard_original
    assert not list(tmp_path.glob(".*.new.*"))
    assert not list(tmp_path.glob(".*.rollback.*"))


def test_deployment_workflow_tracks_enforcer_and_has_config_rollback_guard():
    workflow = WORKFLOW.read_text()

    assert "- 'wtyj/scripts/ensure_dashboard_nginx.py'" in workflow
    assert "trap restore_nginx_on_exit 0" in workflow
    assert 'NGINX_API_REAL=$(readlink -f "$NGINX_API_SITE")' in workflow
    assert "DASHBOARD_HOST_DECLARATIONS" in workflow
    assert "DASHBOARD_APP_ROOT_COUNT" in workflow
    assert "grep -qi 'conflicting server name'" in workflow
    assert "pnpm --filter @workspace/unboks test" in workflow


def _workflow_awk_program(variable: str) -> str:
    workflow = WORKFLOW.read_text()
    match = re.search(
        rf"{variable}=\$\(awk '\n(?P<program>.*?)\n\s*' \"\$[A-Z_]+\"\)",
        workflow,
        flags=re.DOTALL,
    )
    assert match, f"{variable} awk program is missing"
    return match.group("program")


def _run_awk(program: str, contents: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["awk", program],
        input=contents,
        text=True,
        capture_output=True,
        check=False,
    )


def test_dashboard_layout_counts_support_https_and_certbot_redirect_servers():
    config = """server {
    server_name dashboard.unboks.org;
    root /var/www/unboks-dashboard/current;
}
server {
    listen 80;
    server_name dashboard.unboks.org;
    return 404;
}
"""

    hosts = _run_awk(
        _workflow_awk_program("DASHBOARD_HOST_DECLARATIONS"),
        config,
    )
    roots = _run_awk(
        _workflow_awk_program("DASHBOARD_APP_ROOT_COUNT"),
        config,
    )

    assert hosts.returncode == 0, hosts.stderr
    assert hosts.stdout == "2\n"
    assert roots.returncode == 0, roots.stderr
    assert roots.stdout == "1\n"


def test_ali_location_count_is_scoped_to_api_config_file():
    config = """server {
    location ^~ /api/ali-car-rental/ {
        proxy_pass http://ali;
    }
    location /api/another-tenant/ {
        proxy_pass http://another;
    }
}
"""

    locations = _run_awk(
        _workflow_awk_program("ALI_LOCATION_COUNT"),
        config,
    )

    assert locations.returncode == 0, locations.stderr
    assert locations.stdout == "1\n"
