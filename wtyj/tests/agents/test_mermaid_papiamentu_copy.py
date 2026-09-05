"""Static regressions for Mermaid's customer-facing Curaçao Papiamentu copy.

These checks preserve reviewed Mermaid terminology and prevent recorded
spelling, informal-register, and language-mixing defects from returning. They
do not classify every legitimate Papiamentu word or claim native review.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path

from agents.social import mermaid_document_copy
from agents.social import mermaid_documents
from agents.social import mermaid_model_recovery
from agents.social import mermaid_reservation_workflow


ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "clients" / "mermaid" / "config"
PAP_WHEELCHAIR_ACK = (
    "Sí, no tin problema. Nos ta prepará pa risibí bishitantenan ku ta usa stul di rueda. "
    "Mi a registrá un nota pa e tripulashon por prepará pa duna asistensia."
)
PAP_WHEELCHAIR_WITHDRAWAL = (
    "Mi a komprondé. Mi a kita e nota tokante e stul di rueda for di e reservashon aki."
)


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _strings(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _strings(nested)


def _load(name: str) -> dict:
    return json.loads((CONFIG / name).read_text())


def _deterministic_papiamentu_copy() -> list[str]:
    client = _load("client.json")
    catalog = _load("reservation_catalog.json")
    policy = _load("response_policy.json")
    sources = (
        client["mermaid_document_cards"]["copies"]["pap"],
        catalog["guest_copy"]["pap"],
        policy["copies"]["pap"],
        policy["glossary"]["pap"],
        mermaid_document_copy.DOCUMENT_NOTICES["pap"],
        mermaid_documents.LABELS["pap"],
        mermaid_documents.DOCUMENT_COPY["pap"],
        mermaid_model_recovery.FAILURE_COPY["pap"],
        mermaid_model_recovery.HUMAN_COPY["pap"],
        mermaid_reservation_workflow.COPY["pap"],
        mermaid_reservation_workflow.WELCOME_COPY["pap"],
        mermaid_reservation_workflow.WHEELCHAIR_COPY["pap"],
        mermaid_reservation_workflow.WHEELCHAIR_WITHDRAWAL_COPY["pap"],
        mermaid_reservation_workflow.NO_WHEELCHAIR_NOTE_COPY["pap"],
        mermaid_reservation_workflow.BOARDING_ASSISTANCE_COPY["pap"],
        mermaid_reservation_workflow.SUMMARY_COPY["pap"],
        mermaid_reservation_workflow.FAQ_COPY["pap"],
        mermaid_reservation_workflow.PAYMENT_COPY["pap"],
    )
    return [text for source in sources for text in _strings(source)]


def test_known_nonstandard_and_unnecessary_mixed_terms_do_not_return():
    joined = "\n".join(_deterministic_papiamentu_copy())
    for term in (
        "huésped", "wordu", "live", "pickup", "berdat",
        "kombersashon", "período", "movilidat", "aworaki", "prepara",
        "adjuntá", "beach house", "máx.", "katálogo", "lansementu", "pet",
    ):
        assert not re.search(rf"(?<!\w){term}(?!\w)", joined, re.IGNORECASE), term


def test_formal_wheelchair_copy_and_glossary_are_consistent():
    policy = _load("response_policy.json")
    glossary = policy["glossary"]["pap"]

    assert policy["version"] == "mermaid-response-policy-342-v5"
    assert "native_review" not in policy
    assert policy["language_review"]["pap"] == {
        "status": "formal_written_curacao_reference_review_complete",
        "standard": "Fundashon pa Planifikashon di Idioma, Ortografia i Lista di palabra Papiamentu",
        "register": "professional_written_curacao_papiamentu",
        "reviewed_scope": "deterministic production copy and generated-output instructions",
    }
    assert {
        "guest": "bishitante",
        "wheelchair": "stul di rueda",
        "crew": "tripulashon",
        "assistance": "asistensia",
        "current_availability": "disponibilidat aktual",
        "towel": "toaya",
    }.items() <= glossary.items()
    assert glossary["wheelchair_assistance_example"] == PAP_WHEELCHAIR_ACK
    assert glossary["wheelchair_withdrawal_example"] == PAP_WHEELCHAIR_WITHDRAWAL
    assert mermaid_reservation_workflow.WHEELCHAIR_COPY["pap"] == PAP_WHEELCHAIR_ACK
    assert (
        mermaid_reservation_workflow.WHEELCHAIR_WITHDRAWAL_COPY["pap"]
        == PAP_WHEELCHAIR_WITHDRAWAL
    )


def test_fixed_summary_faq_and_document_copy_use_standard_terms():
    catalog = _load("reservation_catalog.json")
    policy = _load("response_policy.json")

    assert mermaid_reservation_workflow.SUMMARY_COPY["pap"]["guests"] == "Bishitantenan"
    assert "toaya" in mermaid_reservation_workflow.FAQ_COPY["pap"]["bring"].casefold()
    assert "disponibilidat aktual" in mermaid_reservation_workflow.PAYMENT_COPY["pap"][0]
    assert mermaid_documents.LABELS["pap"]["customer"] == "Bishitante"
    assert mermaid_documents.LABELS["pap"]["guests"] == "Bishitantenan"
    assert "buska bo na bo alohamentu" in mermaid_documents.LABELS["pap"]["pickup"]
    assert mermaid_documents.DOCUMENT_COPY["pap"]["bring_items"][0] == "Toaya"
    assert mermaid_documents.DOCUMENT_COPY["pap"]["catalog"] == "Katalòk"
    assert "promé ku lansamentu" in mermaid_documents.DOCUMENT_COPY["pap"]["insurance"]
    assert "prepará bo oferta" in mermaid_reservation_workflow.COPY["pap"]["intro"]
    assert "kas di playa" in mermaid_reservation_workflow.FAQ_COPY["pap"]["included"]
    assert catalog["guest_copy"]["pap"]["pickup_car"] == (
        "Transporte ku outo (máksimo {capacity} persona)"
    )
    assert catalog["guest_copy"]["pap"]["pickup_van"] == (
        "Transporte ku vèn (máksimo {capacity} persona)"
    )
    assert mermaid_reservation_workflow.COPY["pap"]["hotel"].startswith("Na ki hotèl")
    assert "asistensia èkstra" in mermaid_reservation_workflow.BOARDING_ASSISTANCE_COPY["pap"]
    assert policy["glossary"]["pap"]["paid_drinks_example"] == (
        "Serbes i biña ta kosta èkstra."
    )


def test_mermaid_fare_wine_and_cash_copy_uses_contextual_preferred_terms():
    policy = _load("response_policy.json")
    glossary = policy["glossary"]["pap"]

    assert "mucha di 0 te ku 3 aña" in glossary["party_question"]
    assert glossary["wine"] == "biña"
    assert glossary["cash"] == "sèn kèsh"
    assert glossary["cap"] == "pèchi"
    assert "biña" in glossary["cash_for_optional_drinks_example"]
    assert "pèchi" in glossary["bring_example"]
    assert mermaid_documents.DOCUMENT_COPY["pap"]["bring_items"][-1] == (
        "Sombré òf pèchi"
    )
