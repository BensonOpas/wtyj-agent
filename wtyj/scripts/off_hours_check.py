#!/usr/bin/env python3
"""Off-hours enforcement for production deploys.
Blocks deploys during Curaçao business hours (05:30-20:00 AST, no DST).
Bypass: include [HOTFIX] in the commit SUBJECT LINE (first line only).
Exits 0 when deploy is allowed, 1 when blocked (reason printed to stdout).
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


CURACAO = ZoneInfo("America/Curacao")
CURACAO_START = 5 * 60 + 30   # 05:30
CURACAO_END   = 20 * 60       # 20:00 (exclusive)


def _hotfix_in_subject(commit_message: str) -> bool:
    """Only the first line (subject) counts. Body text mentions don't bypass."""
    subject = commit_message.split("\n", 1)[0]
    return "[HOTFIX]" in subject


def is_deploy_blocked(now_utc: datetime, commit_message: str) -> tuple[bool, str]:
    """Return (blocked, reason). blocked=True means refuse production deploy."""
    if _hotfix_in_subject(commit_message):
        return (False, "HOTFIX bypass — proceeding during business hours")
    cura = now_utc.astimezone(CURACAO)
    mod = cura.hour * 60 + cura.minute
    if CURACAO_START <= mod < CURACAO_END:
        return (True,
                f"Blocked: Curaçao business hours "
                f"({cura.strftime('%H:%M')} AST). "
                f"Bypass: [HOTFIX] in commit subject line.")
    return (False,
            f"Off-hours (Curaçao {cura.strftime('%H:%M')}) — proceeding")


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
