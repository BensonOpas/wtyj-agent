from datetime import datetime, timezone
from scripts.off_hours_check import is_deploy_blocked


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 4, 14, hour, minute, tzinfo=timezone.utc)


def test_blocked_during_curacao_business_hours():
    blocked, reason = is_deploy_blocked(_utc(15, 0), "Brief 196: ship")
    assert blocked is True
    assert "Curaçao business hours" in reason


def test_not_blocked_outside_business_hours():
    blocked, reason = is_deploy_blocked(_utc(2, 0), "Brief 196: ship")
    assert blocked is False
    assert "Off-hours" in reason


def test_hotfix_in_subject_bypasses():
    blocked, reason = is_deploy_blocked(_utc(15, 0), "Brief 200: [HOTFIX] auth")
    assert blocked is False
    assert "HOTFIX bypass" in reason


def test_hotfix_only_in_body_does_not_bypass():
    msg = "Brief 196: ship feature\n\nThis adds [HOTFIX] bypass docs."
    blocked, reason = is_deploy_blocked(_utc(15, 0), msg)
    assert blocked is True
    assert "Curaçao business hours" in reason


def test_curacao_boundary_exit_allowed():
    blocked, _ = is_deploy_blocked(_utc(0, 0), "Brief 196: ship")
    assert blocked is False
