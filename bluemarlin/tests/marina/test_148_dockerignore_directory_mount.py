"""
Brief 148 — .dockerignore + directory-mount refactor regression tests.

Guards against:
1. Re-introducing runtime config into the Docker build context
   (bluemarlin/config/, bluemarlin/data/, bluemarlin/logs/ must stay excluded)
2. Regression to per-file mounts in either docker-compose.yml
3. Loss of critical preserved settings (env_file, credentials env var,
   image ref, port mapping, data/logs mounts)
4. Deletion of Brief 142's existing .dockerignore patterns.

All tests read files from disk. No Docker daemon required.
"""
import os

# Locate repo root by walking up from this test file
_TEST_FILE = os.path.abspath(__file__)
_BM_TESTS = os.path.dirname(os.path.dirname(_TEST_FILE))  # bluemarlin/tests
_BM_ROOT = os.path.dirname(_BM_TESTS)                      # bluemarlin
_REPO_ROOT = os.path.dirname(_BM_ROOT)                     # repo root

DOCKERIGNORE_PATH = os.path.join(_REPO_ROOT, ".dockerignore")
BM_COMPOSE_PATH = os.path.join(_REPO_ROOT, "docker-compose.yml")
ADAMUS_COMPOSE_PATH = os.path.join(_REPO_ROOT, "clients", "adamus", "docker-compose.yml")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _lines(path):
    """Return .dockerignore lines with blanks and comments stripped."""
    result = []
    for line in _read(path).splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            result.append(stripped)
    return result


# ---------------------------------------------------------------------------
# .dockerignore tests
# ---------------------------------------------------------------------------

def test_dockerignore_excludes_bluemarlin_config():
    """The core fix: runtime config must be excluded from the build context."""
    lines = _lines(DOCKERIGNORE_PATH)
    assert "bluemarlin/config/" in lines, \
        f".dockerignore must contain 'bluemarlin/config/' as a full line. Got: {lines}"


def test_dockerignore_excludes_bluemarlin_data():
    lines = _lines(DOCKERIGNORE_PATH)
    assert "bluemarlin/data/" in lines, \
        f".dockerignore must contain 'bluemarlin/data/' as a full line. Got: {lines}"


def test_dockerignore_excludes_bluemarlin_logs():
    lines = _lines(DOCKERIGNORE_PATH)
    assert "bluemarlin/logs/" in lines, \
        f".dockerignore must contain 'bluemarlin/logs/' as a full line. Got: {lines}"


def test_dockerignore_excludes_clients_dir():
    """Defensive: per-client trees should never be copied into BlueMarlin's image."""
    lines = _lines(DOCKERIGNORE_PATH)
    assert "clients/" in lines, \
        f".dockerignore must contain 'clients/' as a full line. Got: {lines}"


def test_dockerignore_excludes_ds_store():
    lines = _lines(DOCKERIGNORE_PATH)
    assert "**/.DS_Store" in lines, \
        f".dockerignore must contain '**/.DS_Store' as a full line. Got: {lines}"


def test_dockerignore_preserves_brief_142_exclusions():
    """Regression guard: all pre-existing exclusions from Brief 142 must still be present."""
    lines = _lines(DOCKERIGNORE_PATH)
    required = [
        "bluemarlin/backups/",
        "bluemarlin/tests/",
        "bluemarlin/briefs/",
        "bluemarlin/src/",
        "**/__pycache__/",
        "**/.pytest_cache/",
        "*.pyc",
        ".git/",
    ]
    missing = [r for r in required if r not in lines]
    assert not missing, f"Brief 142 exclusions dropped from .dockerignore: {missing}"


# ---------------------------------------------------------------------------
# BlueMarlin docker-compose.yml tests
# ---------------------------------------------------------------------------

def test_bluemarlin_docker_compose_has_config_directory_mount():
    """The new directory mount must be present."""
    content = _read(BM_COMPOSE_PATH)
    assert "./bluemarlin/config:/app/config:rw" in content, \
        "BlueMarlin docker-compose.yml missing directory mount './bluemarlin/config:/app/config:rw'"


def test_bluemarlin_docker_compose_no_per_file_mounts():
    """Regression guard: old per-file mounts must be gone."""
    content = _read(BM_COMPOSE_PATH)
    forbidden = [
        "./bluemarlin/config/client.json:/app/config/client.json",
        "./bluemarlin/config/calendar-key.json:/app/config/calendar-key.json",
        "./bluemarlin/config/azure_refresh_token.txt:/app/config/azure_refresh_token.txt",
    ]
    present = [f for f in forbidden if f in content]
    assert not present, f"BlueMarlin docker-compose.yml still has old per-file mounts: {present}"


def test_bluemarlin_docker_compose_preserves_data_and_logs_mounts():
    content = _read(BM_COMPOSE_PATH)
    assert "./bluemarlin/data:/app/data" in content, "BlueMarlin data mount missing"
    assert "./bluemarlin/logs:/app/logs" in content, "BlueMarlin logs mount missing"


def test_bluemarlin_docker_compose_preserves_env_file():
    content = _read(BM_COMPOSE_PATH)
    assert "./bluemarlin/config/platform.env" in content, \
        "BlueMarlin env_file directive missing or changed path"


def test_bluemarlin_docker_compose_preserves_credentials_env_var():
    """The GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE env var must still point at the new filename."""
    content = _read(BM_COMPOSE_PATH)
    assert "GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE=/app/config/calendar-key.json" in content, \
        "BlueMarlin credentials env var missing or wrong path"


# ---------------------------------------------------------------------------
# Adamus docker-compose.yml tests
# ---------------------------------------------------------------------------

def test_adamus_docker_compose_has_config_directory_mount():
    content = _read(ADAMUS_COMPOSE_PATH)
    assert "./config:/app/config:rw" in content, \
        "Adamus docker-compose.yml missing directory mount './config:/app/config:rw'"


def test_adamus_docker_compose_no_per_file_mounts():
    content = _read(ADAMUS_COMPOSE_PATH)
    forbidden = [
        "./config/client.json:/app/config/client.json",
        "./config/calendar-key.json:/app/config/calendar-key.json",
    ]
    present = [f for f in forbidden if f in content]
    assert not present, f"Adamus docker-compose.yml still has old per-file mounts: {present}"


def test_adamus_docker_compose_preserves_data_and_logs_mounts():
    content = _read(ADAMUS_COMPOSE_PATH)
    assert "./data:/app/data" in content, "Adamus data mount missing"
    assert "./logs:/app/logs" in content, "Adamus logs mount missing"


def test_adamus_docker_compose_preserves_image_ref():
    """Regression guard: Adamus must use the pre-built image, not start rebuilding its own."""
    content = _read(ADAMUS_COMPOSE_PATH)
    assert "image: root-bluemarlin" in content, "Adamus image ref missing or changed"
    assert "build:" not in content, "Adamus docker-compose.yml added a build: directive"


def test_adamus_docker_compose_preserves_port_mapping():
    content = _read(ADAMUS_COMPOSE_PATH)
    assert '"8002:8001"' in content, "Adamus port mapping 8002:8001 missing"
