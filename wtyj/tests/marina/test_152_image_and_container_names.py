"""
Brief 152 — Docker image + container name rename regression tests.
Guards against reverting wtyj-agent / wtyj-bluemarlin / wtyj-adamus back
to the old root-bluemarlin / bluemarlin-default / bluemarlin-adamus names.
"""
import os

_TEST_FILE = os.path.abspath(__file__)
_WTYJ_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_TEST_FILE)))
_REPO_ROOT = os.path.dirname(_WTYJ_ROOT)

BM_COMPOSE = os.path.join(_REPO_ROOT, "clients", "bluemarlin", "docker-compose.yml")
ADAMUS_COMPOSE = os.path.join(_REPO_ROOT, "clients", "adamus", "docker-compose.yml")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# BlueMarlin compose
# ---------------------------------------------------------------------------

def test_bluemarlin_compose_image_is_wtyj_agent():
    content = _read(BM_COMPOSE)
    assert "image: wtyj-agent" in content, "BlueMarlin image must be wtyj-agent"


def test_bluemarlin_compose_container_name_is_wtyj_bluemarlin():
    content = _read(BM_COMPOSE)
    assert "container_name: wtyj-bluemarlin" in content, \
        "BlueMarlin container_name must be wtyj-bluemarlin"


def test_bluemarlin_compose_no_legacy_names():
    """Forbid any reference to old root-bluemarlin image or bluemarlin-default container."""
    content = _read(BM_COMPOSE)
    assert "root-bluemarlin" not in content, "Legacy image name still present"
    assert "bluemarlin-default" not in content, "Legacy container_name still present"


# ---------------------------------------------------------------------------
# Adamus compose
# ---------------------------------------------------------------------------

def test_adamus_compose_image_is_wtyj_agent():
    content = _read(ADAMUS_COMPOSE)
    assert "image: wtyj-agent" in content, "Adamus image must be wtyj-agent"


def test_adamus_compose_container_name_is_wtyj_adamus():
    content = _read(ADAMUS_COMPOSE)
    assert "container_name: wtyj-adamus" in content, \
        "Adamus container_name must be wtyj-adamus"


def test_adamus_compose_no_legacy_names():
    """Forbid any reference to old root-bluemarlin image or bluemarlin-adamus container."""
    content = _read(ADAMUS_COMPOSE)
    assert "root-bluemarlin" not in content, "Legacy image name still present"
    assert "bluemarlin-adamus" not in content, "Legacy container_name still present"


def test_both_composes_use_same_image():
    """Both clients must pull from the same wtyj-agent image — that's the whole
    point of Brief 148's multi-client architecture. If they diverge, something's wrong."""
    bm = _read(BM_COMPOSE)
    ad = _read(ADAMUS_COMPOSE)
    assert "image: wtyj-agent" in bm
    assert "image: wtyj-agent" in ad
