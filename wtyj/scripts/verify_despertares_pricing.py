"""Opt-in, no-delivery pricing replay against the tenant's configured model.

Run inside the tenant container. Optional --candidate loads a source file into
this diagnostic process only, without replacing code used by live workers.
Reads tenant knowledge through SQLite mode=ro. No conversation or task writes,
no provider send, no real patient history. Makes up to nine model calls.
"""
import argparse
import ast
import json
import re
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, "/app")

parser = argparse.ArgumentParser()
parser.add_argument("--candidate")
parser.add_argument("--candidate-state")
parser.add_argument("--case", default="all")
args = parser.parse_args()

from agents.marina import marina_agent as agent
from shared import state_registry, tenant_hard_rules

if not tenant_hard_rules.is_consulta_despertares():
    raise SystemExit("Refusing: this verifier is only for consulta-despertares")
if args.candidate:
    exec(compile(Path(args.candidate).read_text(), args.candidate, "exec"), agent.__dict__)
if args.candidate_state:
    source = Path(args.candidate_state).read_text()
    function = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "get_active_info_updates")
    exec(compile(ast.Module(body=[function], type_ignores=[]), args.candidate_state, "exec"), state_registry.__dict__)

state_registry._get_conn = lambda: sqlite3.connect(
    "file:/app/data/state_registry.db?mode=ro", uri=True,
)
agent.bm_logger.log = lambda *a, **kw: None  # do not mix test usage into customer logs
notes = state_registry.get_active_info_updates(newest_edit_first=True)
live_note_loader = state_registry.get_active_info_updates

cases = [
    ("adult-price", "Necesito consulta para adulto y quiero saber precio por consulta", [], "50"),
    ("website-price", "Hola Consulta Psicológica Despertares. Necesito más información sobre Psicólogo Leganés. Hola quería saber cuánto cuesta la sesión", [], "50"),
    ("couples-price", "¿Cuánto cuesta cada sesión de terapia de pareja?", [], "70"),
    ("family-price", "¿Cuánto cuesta la terapia familiar?", [], "80"),
    ("online-first", "¿La primera sesión online también es gratuita?", [], "free"),
    ("stale-ai-price", "¿Seguro? Me habías dicho otra cantidad. ¿Cuál es el precio correcto de la sesión individual?", [
        {"role": "user", "text": "¿Cuánto cuesta la sesión individual?"},
        {"role": "assistant", "text": "La sesión individual cuesta 60 €."},
    ], "50"),
    ("unknown-price", "¿Cuánto cuesta una sesión de terapia de grupo? Quiero el precio exacto.", [], "unknown"),
    ("baseline-gap", "¿Cuánto cuesta una sesión individual de adultos a partir de la segunda?", [], "50"),
    ("new-price-override", "¿Cuánto cuesta ahora la sesión individual?", [], "55"),
]
if args.case != "all":
    cases = [c for c in cases if c[0] == args.case]


def run(case):
    name, body, history, expected = case
    result = agent.process_message(
        from_email="pricing-verification-no-delivery", subject="", body=body,
        thread_fields={}, thread_flags={}, channel="whatsapp", messages=history,
    )
    reply = result.get("reply", "")
    amounts = re.findall(r"\b(\d+)(?:[.,]00)?\s*(?:€|euros?\b)", reply, re.I)
    passed = expected in amounts if expected not in {"free", "unknown"} else (
        ("gratuit" in reply.lower() or "gratis" in reply.lower())
        if expected == "free" else not amounts
    )
    if expected not in {"free", "unknown"}:
        passed = passed and not result.get("requires_human") and not result.get("relay_question")
    if name == "family-price":
        passed = passed and "70" not in amounts
    if name == "new-price-override":
        passed = passed and "50" not in amounts
    print(json.dumps({"case": name, "passed": passed, "reply": reply,
                      "requires_human": result.get("requires_human"),
                      "relay_question": result.get("relay_question")}, ensure_ascii=False), flush=True)
    return passed


normal = [c for c in cases if c[0] not in {"baseline-gap", "new-price-override"}]
with ThreadPoolExecutor(max_workers=2) as pool:
    outcomes = list(pool.map(run, normal))
for case in cases:
    if case[0] == "baseline-gap":
        # Before Roberto added actual numeric tariffs: generic price notes
        # remain. Keep real operator notes immutable; filter in memory only.
        state_registry.get_active_info_updates = lambda **kw: [
            n for n in notes if not (n.get("type") == "pricing" and "€" in n.get("text", ""))
        ]
        outcomes.append(run(case))
    elif case[0] == "new-price-override":
        state_registry.get_active_info_updates = lambda **kw: [{
            "type": "pricing", "text": "Nueva tarifa de sesión individual: 55 €. Sustituye únicamente la tarifa individual anterior."
        }] + notes
        outcomes.append(run(case))
state_registry.get_active_info_updates = live_note_loader
print(json.dumps({"passed": sum(outcomes), "total": len(outcomes), "delivered_messages": 0}), flush=True)
raise SystemExit(0 if all(outcomes) else 1)
