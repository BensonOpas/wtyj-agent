#!/usr/bin/env python3
"""J3-N2-03: in-container verification helper for ICP override consumption.

Usage (inside a running Nr 2 container):

    docker exec wtyj-unboks python3 scripts/verify_icp_overrides.py
    docker exec wtyj-unboks python3 scripts/verify_icp_overrides.py --json

Prints a human-readable summary of the current ICP override envelope
the Marina runtime would see for THIS container's tenant, plus
per-field 'would_apply' flags showing whether the prompt builders
would actually consume each override.

Read-only. Never writes. Never prints the bridge token. Runs in the
live container's process space so the icp_overrides 60s cache state
is the one the agent itself sees.

The shell-access requirement is the gate; no env flag needed here.
"""
import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only ICP override verification for marina_agent.")
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON only (machine-readable). Default: human-readable.")
    parser.add_argument(
        "--fresh", action="store_true",
        help="Clear the in-process cache before fetching so the result "
             "reflects the bridge state RIGHT NOW (not the cached snapshot).")
    args = parser.parse_args()

    try:
        from shared import icp_overrides
    except ImportError as exc:
        sys.stderr.write(
            f"ERR: cannot import shared.icp_overrides: {exc}\n"
            "Are you running this inside the container? "
            "(docker exec wtyj-unboks python3 scripts/verify_icp_overrides.py)\n")
        return 2

    if args.fresh:
        icp_overrides.clear_cache()

    envelope = icp_overrides.fetch_overrides()

    # Curate into the same shape as the /icp-overrides-debug endpoint.
    ai = envelope.get("ai_agent_settings") or {}
    tone = ai.get("tone") if isinstance(ai, dict) else None
    rules = ai.get("escalation_rules") if isinstance(ai, dict) else None
    sot_entries = envelope.get("sot_entries") or []
    if not isinstance(sot_entries, list):
        sot_entries = []

    sot_visible = [
        e for e in sot_entries
        if isinstance(e, dict)
        and (e.get("title") or "").strip()
        and (e.get("content") or "").strip()
    ]

    # J3-N2-04: pull the in-process observability state captured
    # during the fetch_overrides() call above. Per-process scope: this
    # reflects THIS CLI invocation, not the agent's process.
    observability = icp_overrides.get_observability_state()
    summary = {
        "tenant_id": envelope.get("tenant_id"),
        "bridge_available": bool(envelope.get("available")),
        "bridge_reason": envelope.get("reason"),
        "observability": observability,
        "ai_tone": _tone_view(tone),
        "ai_escalation_rules": _rules_view(rules),
        "sot_entries": {
            "count": len(sot_visible),
            "titles": [
                {"title": (e.get("title") or "").strip(),
                 "category": (e.get("category") or "general").strip(),
                 "source": e.get("source")}
                for e in sot_visible
            ],
            "would_apply": len(sot_visible) > 0,
        },
        "env_check": {
            "NR3_INTERNAL_OVERRIDES_URL_set": bool(
                os.environ.get("NR3_INTERNAL_OVERRIDES_URL", "").strip()),
            "NR3_INTERNAL_API_TOKEN_set": bool(
                os.environ.get("NR3_INTERNAL_API_TOKEN", "").strip()),
            "TENANT_ID": os.environ.get("TENANT_ID", "").strip() or "(unset)",
        },
    }

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
        return 0

    _print_human(summary)
    return 0


def _tone_view(tone):
    if isinstance(tone, dict):
        v = (tone.get("tone") or "").strip()
        return {
            "value": tone.get("tone"),
            "notes": tone.get("notes"),
            "source": tone.get("source"),
            "updated_at": tone.get("updated_at"),
            "updated_by": tone.get("updated_by"),
            "would_apply": bool(v),
        }
    return {"value": None, "source": "backend", "would_apply": False}


def _rules_view(rules):
    if isinstance(rules, dict):
        soft = rules.get("soft_escalation") or {}
        hard = rules.get("hard_escalation") or {}
        return {
            "soft_escalation": {"enabled": bool(soft.get("enabled")),
                                  "when": soft.get("when")},
            "hard_escalation": {"enabled": bool(hard.get("enabled")),
                                  "when": hard.get("when")},
            "source": rules.get("source"),
            "updated_at": rules.get("updated_at"),
            "updated_by": rules.get("updated_by"),
            "would_apply": bool(
                soft.get("enabled") or hard.get("enabled")
                or (soft.get("when") or "").strip()
                or (hard.get("when") or "").strip()),
        }
    return {"value": None, "source": "backend", "would_apply": False}


def _print_human(s: dict) -> None:
    print("=" * 60)
    print(" Nr 2 ICP override verification (J3-N2-03/04)")
    print("=" * 60)
    print(f" Tenant:           {s['tenant_id']!r}")
    print(f" Bridge available: {s['bridge_available']}")
    if not s["bridge_available"]:
        print(f" Bridge reason:    {s['bridge_reason']}")
    e = s["env_check"]
    print(f" Env:              URL_set={e['NR3_INTERNAL_OVERRIDES_URL_set']}  "
            f"TOKEN_set={e['NR3_INTERNAL_API_TOKEN_set']}  "
            f"TENANT_ID={e['TENANT_ID']}")
    print()
    print("-- OBSERVABILITY (this CLI process only) --")
    o = s.get("observability") or {}
    print(f"  last_fetch_at:       {o.get('last_fetch_at')}")
    print(f"  last_outcome:        {o.get('last_outcome')!r}")
    print(f"  last_duration_ms:    {o.get('last_fetch_duration_ms')}")
    print(f"  last_tone_source:    {o.get('last_tone_source')!r}")
    print(f"  last_escalation:     {o.get('last_escalation_source')!r}")
    print(f"  last_sot_count:      {o.get('last_sot_count')}")
    print(f"  total_fetches:       {o.get('total_fetches')}  "
            f"(failures: {o.get('total_failures')}, "
            f"cache_hits: {o.get('total_cache_hits')})")
    print("  NOTE: these counters are per-process. The agent's container")
    print("  has its own counters; use the HTTP debug endpoint for those.")
    print()
    print("-- AI TONE --")
    t = s["ai_tone"]
    print(f"  source:       {t.get('source')!r}")
    print(f"  value:        {t.get('value')!r}")
    if t.get("notes"):
        print(f"  notes:        {t['notes']!r}")
    if t.get("updated_by"):
        print(f"  updated_by:   {t['updated_by']}")
        print(f"  updated_at:   {t.get('updated_at')}")
    print(f"  would_apply:  {t['would_apply']}")
    print()
    print("-- AI ESCALATION RULES --")
    r = s["ai_escalation_rules"]
    print(f"  source:       {r.get('source')!r}")
    if "soft_escalation" in r:
        soft = r["soft_escalation"]
        hard = r["hard_escalation"]
        print(f"  soft escalation:  enabled={soft['enabled']}  "
                f"when={(soft.get('when') or '')!r}")
        print(f"  hard escalation:  enabled={hard['enabled']}  "
                f"when={(hard.get('when') or '')!r}")
        if r.get("updated_by"):
            print(f"  updated_by:   {r['updated_by']}")
            print(f"  updated_at:   {r.get('updated_at')}")
    else:
        print("  (no ICP override; agent uses backend escalation_tone)")
    print(f"  would_apply:  {r['would_apply']}")
    print()
    print("-- SOURCE OF TRUTH ENTRIES --")
    sot = s["sot_entries"]
    print(f"  count:        {sot['count']}")
    if sot["count"]:
        for entry in sot["titles"]:
            print(f"    - [{entry['category']}] {entry['title']}  "
                    f"(source={entry['source']})")
    print(f"  would_apply:  {sot['would_apply']}")
    print()
    print("=" * 60)
    # Final one-line verdict for the eyeball check
    icp_active = (s["ai_tone"]["would_apply"]
                   or s["ai_escalation_rules"]["would_apply"]
                   or s["sot_entries"]["would_apply"])
    if not s["bridge_available"]:
        print(" VERDICT: bridge OFFLINE - agent using backend defaults.")
    elif icp_active:
        print(" VERDICT: bridge ONLINE - ICP overrides ARE being consumed.")
    else:
        print(" VERDICT: bridge ONLINE - no active ICP overrides (backend "
                "defaults in use).")
    print("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
