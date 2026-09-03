import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPTS = Path(__file__).parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("prepare_mermaid_reservation_release", SCRIPTS / "prepare_mermaid_reservation_release.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_merge_preserves_all_live_credentials_bindings_and_other_features():
    source = json.loads((Path(__file__).parents[3] / "clients/mermaid/config/client.json").read_text())
    live = copy.deepcopy(source)
    live.update(password="protected", access_key="protected-key", channel_account_allowlist={"mode": "strict", "zernio_accounts": ["exact-account"]})
    live["features"]["other_feature"] = True
    live["social_profiles"] = {"facebook": {"id": "do-not-change"}}
    original = copy.deepcopy(live)
    result = MODULE.merged_config(live, source)
    assert live == original
    assert result["password"] == original["password"]
    assert result["access_key"] == original["access_key"]
    assert result["channel_account_allowlist"] == original["channel_account_allowlist"]
    assert result["social_profiles"] == original["social_profiles"]
    assert result["features"]["other_feature"] is True
    assert result["features"]["mermaid_reminders"] is False


@pytest.mark.parametrize("slug,accounts", [("ali-car-rental", ["one"]), ("mermaid", []), ("mermaid", ["one", "two"])])
def test_merge_rejects_wrong_tenant_or_account_binding(slug, accounts):
    with pytest.raises(ValueError):
        MODULE.merged_config({"slug": slug, "channel_account_allowlist": {"mode": "strict", "zernio_accounts": accounts}}, {"slug": "mermaid"})


def test_env_retains_credentials_and_reuses_signing_secret():
    original = "# Protected\nANTHROPIC_API_KEY=keep-it\nMERMAID_DEMO_SIGNING_SECRET=keep-signature\nTENANT_SLUG=mermaid\n"
    prepared = MODULE.prepared_env(original)
    assert "ANTHROPIC_API_KEY=keep-it\n" in prepared
    assert "MERMAID_DEMO_SIGNING_SECRET=keep-signature\n" in prepared
    assert prepared.count("TENANT_SLUG=") == 1
    assert "UNBOKS_PUBLIC_BASE_URL=https://api.unboks.org/api/mermaid\n" in prepared
    assert "TENANT_RUNTIME_CONTROLS_REQUIRED=true\n" in prepared


def test_private_write_is_complete_and_owner_only(tmp_path):
    path = tmp_path / "protected/value"
    MODULE.private_write(path, b"first")
    MODULE.private_write(path, b"replacement")
    assert path.read_bytes() == b"replacement"
    assert path.stat().st_mode & 0o777 == 0o600
    assert list(path.parent.iterdir()) == [path]
