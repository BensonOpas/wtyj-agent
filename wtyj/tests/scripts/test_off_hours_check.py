from datetime import datetime, timezone
from scripts.off_hours_check import is_deploy_blocked


def _utc(hour: int, minute: int = 0) -> datetime:
    # April 14, 2026 — Madrid is CEST (UTC+2), Curaçao is AST (UTC-4)
    return datetime(2026, 4, 14, hour, minute, tzinfo=timezone.utc)


def test_blocked_when_both_timezones_in_business_hours():
    # 15:00 UTC = 17:00 Madrid (blocked), 11:00 Curaçao (blocked)
    blocked, reason = is_deploy_blocked(_utc(15, 0), "Brief 195: ship")
    assert blocked is True
    assert "both timezones" in reason


def test_blocked_curacao_only_late_afternoon():
    # 18:00 UTC = 20:00 Madrid (off, ≥ 18:00), 14:00 Curaçao (blocked)
    blocked, reason = is_deploy_blocked(_utc(18, 0), "Brief 195: ship")
    assert blocked is True
    assert "Curaçao business hours" in reason


def test_blocked_madrid_only_early_morning():
    # 07:00 UTC = 09:00 Madrid (blocked), 03:00 Curaçao (off, < 05:30)
    blocked, reason = is_deploy_blocked(_utc(7, 0), "Brief 195: ship")
    assert blocked is True
    assert "Madrid business hours" in reason


def test_not_blocked_when_both_off_hours():
    # 04:00 UTC = 06:00 Madrid (off), 00:00 Curaçao (off)
    blocked, reason = is_deploy_blocked(_utc(4, 0), "Brief 195: ship")
    assert blocked is False
    assert "Off-hours" in reason


def test_hotfix_bypasses_block():
    # Same as dual-block case but with [HOTFIX] → allowed
    blocked, reason = is_deploy_blocked(_utc(15, 0), "Brief 200: [HOTFIX] patch")
    assert blocked is False
    assert "HOTFIX bypass" in reason


def test_curacao_boundary_exit_allowed():
    # 00:00 UTC = 02:00 Madrid (off), 20:00 Curaçao (exclusive end — off)
    blocked, _ = is_deploy_blocked(_utc(0, 0), "Brief 195: ship")
    assert blocked is False
