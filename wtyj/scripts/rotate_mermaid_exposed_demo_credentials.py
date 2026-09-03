"""Protected one-time Mermaid remediation after the supported password reset.

Requires stopped service, quiescent tenant jobs, and the canonical config lock.
Only rotates this tenant's access/connect credentials and persisted session.
Never prints or exports credentials. The old password reset is handled by Nr3.
"""

import json
from pathlib import Path
import secrets
import subprocess
from datetime import datetime, timezone, timedelta

from prepare_mermaid_reservation_release import private_write
from sync_mermaid_config_fields import _canonical_client_json_lock


def assert_quiet():
    if subprocess.check_output(["docker", "inspect", "wtyj-mermaid", "--format", "{{.State.Running}}"], text=True).strip() != "false":
        raise RuntimeError("Mermaid service must be stopped")
    for path in Path("/root/unboks-internal-control-panel/data/provisioning/jobs").iterdir():
        if path.suffix in {".json", ".processing"}:
            job = json.loads(path.read_text())
            if job.get("slug") == "mermaid":
                raise RuntimeError("Mermaid lifecycle job still active")


def main():
    assert_quiet()
    root = Path("/root/clients/mermaid")
    config = root / "config/client.json"
    session = root / "data/session_token"
    backup = Path("/root/backups/mermaid-reservations/credential-remediation-20260903")
    backup.mkdir(mode=0o700, exist_ok=False)
    with _canonical_client_json_lock(config):
        assert_quiet()
        if config.is_symlink() or session.is_symlink():
            raise RuntimeError("Regular credential files required")
        original = config.read_bytes()
        data = json.loads(original)
        assert data.get("slug") == "mermaid"
        assert data.get("password_updated_at"), "Supported Nr3 password reset required first"
        allowlist = data["channel_account_allowlist"]
        assert allowlist.get("mode") == "strict" and len(allowlist.get("zernio_accounts", [])) == 1
        private_write(backup / "client.before.json", original)
        if session.exists():
            private_write(backup / "session.before", session.read_bytes())
        now = datetime.now(timezone.utc)
        data["access_key"] = secrets.token_urlsafe(24)
        data["whatsapp_connect_token"] = secrets.token_urlsafe(32)
        data["whatsapp_connect_token_expires_at"] = (now + timedelta(days=7)).isoformat()
        data["credential_remediated_at"] = now.isoformat()
        private_write(config, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode())
        private_write(session, secrets.token_hex(32).encode())
        assert json.loads(config.read_text())["channel_account_allowlist"] == allowlist
    print(json.dumps({"rotated_fields": ["access_key", "whatsapp_connect_token", "session_token"], "supported_password_reset_preserved": True, "provider_binding_preserved": True, "backup": str(backup), "secret_output": False}))


if __name__ == "__main__":
    main()
