"""
Brief 151 — source directory rename regression tests.
Guards against: reverting wtyj/ → bluemarlin/ in Dockerfile or .dockerignore.
"""
import os

_TEST_FILE = os.path.abspath(__file__)
_WTYJ_TESTS = os.path.dirname(os.path.dirname(_TEST_FILE))
_WTYJ_ROOT = os.path.dirname(_WTYJ_TESTS)
_REPO_ROOT = os.path.dirname(_WTYJ_ROOT)

DOCKERFILE_PATH = os.path.join(_REPO_ROOT, "Dockerfile")
DOCKERIGNORE_PATH = os.path.join(_REPO_ROOT, ".dockerignore")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def test_wtyj_directory_exists():
    assert os.path.isdir(os.path.join(_REPO_ROOT, "wtyj")), \
        "wtyj/ directory must exist at repo root"


def test_bluemarlin_directory_gone():
    assert not os.path.isdir(os.path.join(_REPO_ROOT, "bluemarlin")), \
        "bluemarlin/ directory must NOT exist after Brief 151 rename"


def test_dockerfile_copies_wtyj():
    content = _read(DOCKERFILE_PATH)
    assert "COPY wtyj/ /app/" in content, "Dockerfile must COPY wtyj/ /app/"


def test_dockerfile_no_bluemarlin_copy():
    content = _read(DOCKERFILE_PATH)
    assert "COPY bluemarlin/" not in content, \
        "Dockerfile must not reference the old bluemarlin/ path"


def test_dockerignore_uses_wtyj_paths():
    lines = [l.strip() for l in _read(DOCKERIGNORE_PATH).splitlines() if l.strip() and not l.strip().startswith("#")]
    required = [
        "wtyj/backups/",
        "wtyj/tests/",
        "wtyj/briefs/",
        "wtyj/config/",
        "wtyj/data/",
        "wtyj/logs/",
    ]
    missing = [r for r in required if r not in lines]
    assert not missing, f".dockerignore missing wtyj/ patterns: {missing}"


def test_dockerignore_no_bluemarlin_paths():
    content = _read(DOCKERIGNORE_PATH)
    # Match the literal path prefix "bluemarlin/" at start of a line
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("bluemarlin/"), \
            f".dockerignore still has legacy bluemarlin/ path: {stripped}"
