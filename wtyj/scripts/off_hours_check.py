#!/usr/bin/env python3
"""Off-hours enforcement for production deploys.
Blocks deploys during EITHER Curaçao business hours (05:30-20:00 AST, no DST)
OR Madrid business hours (09:00-18:00 local, DST-aware).
Bypass by including [HOTFIX] in the commit message.
Exits 0 when deploy is allowed, 1 when blocked (reason printed to stdout).
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


CURACAO = ZoneInfo("America/Curacao")
MADRID = ZoneInfo("Europe/Madrid")

# Minute-of-day boundaries
CURACAO_START = 5 * 60 + 30   # 05:30
CURACAO_END   = 20 * 60       # 20:00 (exclusive)
MADRID_START  = 9 * 60        # 09:00
MADRID_END    = 18 * 60       # 18:00 (exclusive)


def _in_business_hours(local_dt: datetime, start: int, end: int) -> bool:
    mod = local_dt.hour * 60 + local_dt.minute
    return start <= mod < end


def is_deploy_blocked(now_utc: datetime, commit_message: str) -> tuple[bool, str]:
    """Return (blocked, reason). blocked=True means refuse deploy."""
    if "[HOTFIX]" in commit_message:
        return (False, "HOTFIX bypass — proceeding during business hours")

    cura_local = now_utc.astimezone(CURACAO)
    madrid_local = now_utc.astimezone(MADRID)
    cura_blocked = _in_business_hours(cura_local, CURACAO_START, CURACAO_END)
    madrid_blocked = _in_business_hours(madrid_local, MADRID_START, MADRID_END)

    if cura_blocked and madrid_blocked:
        return (True,
                f"Blocked: both timezones in business hours "
                f"(Curaçao {cura_local.strftime('%H:%M')} AST, "
                f"Madrid {madrid_local.strftime('%H:%M')} local). "
                f"Emergency bypass: include [HOTFIX] in commit message.")
    if cura_blocked:
        return (True,
                f"Blocked: Curaçao business hours "
                f"({cura_local.strftime('%H:%M')} AST). "
                f"Bypass: [HOTFIX] in commit message.")
    if madrid_blocked:
        return (True,
                f"Blocked: Madrid business hours "
                f"({madrid_local.strftime('%H:%M')} local). "
                f"Bypass: [HOTFIX] in commit message.")
    return (False,
            f"Off-hours (Curaçao {cura_local.strftime('%H:%M')}, "
            f"Madrid {madrid_local.strftime('%H:%M')}) — proceeding")


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--commit-message", required=True)
    args = p.parse_args()
    blocked, reason = is_deploy_blocked(datetime.now(timezone.utc),
                                        args.commit_message)
    print(reason)
    sys.exit(1 if blocked else 0)


if __name__ == "__main__":
    main()
