"""
Brief 150 — BlueMarlin deployment layout + rebrand tests.

Guards against:
1. Reverting the move back to /root/bluemarlin/config/
2. Re-introducing BlueFinn (real company) references in BlueMarlin's config
3. Regression on the deployment layout: docker-compose, build context, etc.
"""
import json
import os

# Repo-relative paths
_TEST_FILE = os.path.abspath(__file__)
_BM_TESTS = os.path.dirname(os.path.dirname(_TEST_FILE))
_BM_ROOT = os.path.dirname(_BM_TESTS)
_REPO_ROOT = os.path.dirname(_BM_ROOT)

BM_CLIENT_JSON = os.path.join(_REPO_ROOT, "clients", "bluemarlin", "config", "client.json")
BM_COMPOSE = os.path.join(_REPO_ROOT, "clients", "bluemarlin", "docker-compose.yml")
LEGACY_CLIENT_JSON = os.path.join(_BM_ROOT, "config", "client.json")
ROOT_COMPOSE = os.path.join(_REPO_ROOT, "docker-compose.yml")
ROOT_DEPLOY_SH = os.path.join(_REPO_ROOT, "deploy.sh")


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Deployment layout tests
# ---------------------------------------------------------------------------

def test_bluemarlin_config_lives_in_clients_bluemarlin():
    assert os.path.exists(BM_CLIENT_JSON), f"Expected client.json at {BM_CLIENT_JSON}"


def test_bluemarlin_config_not_at_legacy_location():
    assert not os.path.exists(LEGACY_CLIENT_JSON), \
        f"Legacy path still has client.json: {LEGACY_CLIENT_JSON}"


def test_bluemarlin_docker_compose_exists():
    assert os.path.exists(BM_COMPOSE), f"Expected docker-compose.yml at {BM_COMPOSE}"


def test_root_docker_compose_deleted():
    assert not os.path.exists(ROOT_COMPOSE), \
        f"Root docker-compose.yml should be deleted, still at {ROOT_COMPOSE}"


def test_root_deploy_sh_deleted():
    assert not os.path.exists(ROOT_DEPLOY_SH), \
        f"Root deploy.sh should be deleted, still at {ROOT_DEPLOY_SH}"


def test_bluemarlin_docker_compose_has_directory_mount():
    content = _read(BM_COMPOSE)
    assert "./config:/app/config:rw" in content, "Missing config directory mount"


def test_bluemarlin_docker_compose_has_build_context():
    content = _read(BM_COMPOSE)
    assert "context: ../.." in content, \
        "docker-compose.yml must have build.context: ../.. so the Dockerfile at repo root is findable"


def test_bluemarlin_docker_compose_uses_port_8001():
    content = _read(BM_COMPOSE)
    assert '"8001:8001"' in content, "Port mapping 8001:8001 missing"


def test_bluemarlin_docker_compose_image_name():
    content = _read(BM_COMPOSE)
    assert "image: root-bluemarlin" in content, "Image name must be root-bluemarlin"


# ---------------------------------------------------------------------------
# Rebrand tests
# ---------------------------------------------------------------------------

def test_bluemarlin_client_json_name_rebranded():
    cfg = _load_json(BM_CLIENT_JSON)
    name = cfg["business"]["name"]
    assert name == "BlueMarlin Charters", f"Expected BlueMarlin Charters, got {name!r}"
    assert "BlueFinn" not in name


def test_bluemarlin_client_json_email_rebranded():
    cfg = _load_json(BM_CLIENT_JSON)
    email = cfg["business"]["email"]
    assert email == "butlerbensonagent@gmail.com", f"Expected gmail, got {email!r}"
    assert "bluefinncharters" not in email.lower()


def test_bluemarlin_client_json_phone_rebranded():
    cfg = _load_json(BM_CLIENT_JSON)
    phone = cfg["business"]["phone"]
    whatsapp = cfg["business"]["whatsapp"]
    assert phone == "+15155005577", f"Expected +15155005577, got {phone!r}"
    assert whatsapp == "+15155005577", f"Expected +15155005577, got {whatsapp!r}"
    assert "9690 3717" not in phone
    assert "9690 3717" not in whatsapp


def test_bluemarlin_client_json_agent_signature_rebranded():
    cfg = _load_json(BM_CLIENT_JSON)
    sig = cfg["business"]["agent_signature"]
    assert sig.endswith("BlueMarlin Charters"), f"Unexpected agent_signature: {sig!r}"
    assert "BlueFinn" not in sig


def test_bluemarlin_resources_rebranded():
    cfg = _load_json(BM_CLIENT_JSON)
    resources = cfg["resources"]
    assert "bluemarlin1" in resources
    assert "bluemarlin2" in resources
    assert "bluefinn1" not in resources
    assert "bluefinn2" not in resources
    assert resources["bluemarlin1"]["display_name"] == "BlueMarlin 1"
    assert resources["bluemarlin2"]["display_name"] == "BlueMarlin 2"


def test_bluemarlin_klein_curacao_slots_reference_renamed_resources():
    cfg = _load_json(BM_CLIENT_JSON)
    slots = cfg["services"]["klein_curacao"]["slots"]
    for slot in slots:
        res = slot.get("resource", "")
        assert not res.startswith("BlueFinn"), f"Slot resource still references BlueFinn: {res}"
        assert res.startswith("BlueMarlin"), f"Expected BlueMarlin prefix, got {res}"


def test_bluemarlin_client_json_no_bluefinn_references_in_business_and_resources():
    cfg = _load_json(BM_CLIENT_JSON)
    business_text = json.dumps(cfg["business"])
    resources_text = json.dumps(cfg["resources"])
    for section_name, text in [("business", business_text), ("resources", resources_text)]:
        for forbidden in ["BlueFinn", "bluefinn", "bluefinncharters", "9690 3717"]:
            assert forbidden not in text, \
                f"Forbidden string {forbidden!r} found in {section_name} section"


def test_bluemarlin_persona_no_bluefinn_references():
    cfg = _load_json(BM_CLIENT_JSON)
    persona = cfg.get("agent_persona", {})
    freeform = persona.get("freeform_notes", "")
    assert "BlueFinn" not in freeform, \
        f"agent_persona.freeform_notes still mentions BlueFinn: {freeform!r}"
