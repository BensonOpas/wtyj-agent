"""Synthetic-only real-model canary, in a disposable container and data volume.

Never sends a provider message. Requires an explicit isolated-data marker and
patches receipt transport before exercising the signed simulated payment.
"""

import json
import os
from pathlib import Path
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.social import mermaid_reservation_workflow as workflow
from agents.social import mermaid_demo_payment as payment
from agents.social import mermaid_documents as documents
from agents.social import mermaid_reservation_store as reservations
from shared import config_loader, state_registry


def main():
    if os.environ.get("MERMAID_ISOLATED_CANARY") != "synthetic-no-provider-send" or not Path("/app/data/.isolated-canary").is_file():
        raise RuntimeError("Disposable isolated canary data required; never use live data")
    assert config_loader.get_raw().get("slug") == "mermaid"
    today = datetime.now(timezone(timedelta(hours=-4))).date()
    date = (today + timedelta(days=(5 - today.weekday()) % 7 or 7)).isoformat()
    transcripts = []

    def turn(phone, text, index):
        state_registry.dm_store_message(conversation_id=phone, channel="whatsapp", role="user", text=text)
        reply = workflow.handle_demo_message({"from": phone, "text": text, "message_id": f"{phone}-{index}", "from_name": "Synthetic Release Guest"}, include_media=True, use_model=True)
        state_registry.dm_store_message(conversation_id=phone, channel="whatsapp", role="assistant", text=reply["text"])
        transcripts.append({"conversation": phone, "guest": text, "tracy": reply["text"]})
        return reply

    samples = {
        "en": (f"I would like to book {date} for two adults only, no children. My full name is Ana Silva and we will meet at Fishermen's Pier. Please speak English.", "Yes, all details are correct. Please proceed."),
        "nl": (f"Ik wil graag reserveren voor {date}, alleen twee volwassenen, geen kinderen. Mijn volledige naam is Ana Silva. We komen naar Fishermen's Pier. Graag Nederlands.", "Ja, alles klopt. Ga maar verder."),
        "de": (f"Ich möchte für {date} buchen, nur zwei Erwachsene, keine Kinder. Mein vollständiger Name ist Ana Silva. Wir kommen zum Fishermen's Pier. Bitte Deutsch.", "Ja, alle Angaben sind korrekt. Bitte weiter."),
        "es": (f"Quiero reservar para {date}, solo dos adultos, sin niños. Mi nombre completo es Ana Silva y llegaremos a Fishermen's Pier. Habla español por favor.", "Sí, todos los datos son correctos. Continúa."),
        "pap": (f"Mi ke reservá pa {date}, solamente dos adulto, sin mucha. Mi nòmber kompleto ta Ana Silva i nos ta bini Fishermen's Pier. Papia Papiamentu ku mi.", "Si, tur dato ta korekto. Por sigui."),
        "pt": (f"Quero reservar para {date}, apenas dois adultos, sem crianças. Meu nome completo é Ana Silva e iremos ao Fishermen's Pier. Fale português por favor.", "Sim, todos os dados estão corretos. Pode continuar."),
    }
    results = []
    for locale, (request, confirm) in samples.items():
        phone = "synthetic-release-" + locale
        first = turn(phone, request, 1)
        intake = state_registry.wa_get_booking_state(phone)["fields"]["mermaid_intake"]
        assert intake["phase"] == "awaiting_summary_confirmation", (locale, intake)
        assert intake["language"] == locale, (locale, intake["language"])
        assert first["media"] is None
        second = turn(phone, confirm, 2)
        assert second["media"]["type"] == "file", locale
        reservation = reservations.latest_for_conversation(phone)
        assert reservation["state"] == "demo_payment_pending"
        assert reservation["monetary_snapshot"]["total"] == 300
        documents.mark_delivery(second["mermaid_delivery_commit"]["job_id"], True)
        url = payment.build_payment_url(os.environ["UNBOKS_PUBLIC_BASE_URL"], reservation["public_id"], os.environ["MERMAID_DEMO_SIGNING_SECRET"])
        query = parse_qs(urlsplit(url).query)
        expires, signature = int(query["expires"][0]), query["signature"][0]
        assert payment.checkout_page(reservation["public_id"], expires, signature).status_code == 200
        with patch.object(payment, "send_reply", return_value=True) as sender, patch.object(payment.icp_overrides, "fetch_overrides_fresh", return_value={}), patch.object(payment.icp_overrides, "whatsapp_inbox_state", return_value=True), patch.object(payment.icp_overrides, "auto_reply_state", return_value=True):
            assert payment.complete_checkout(reservation["public_id"], expires, signature, "success").status_code == 200
            assert payment.complete_checkout(reservation["public_id"], expires, signature, "success").status_code == 200
            sender.assert_called_once()
            assert sender.call_args.kwargs["attachment_type"] == "file"
        booked = reservations.latest_for_conversation(phone)
        assert booked["state"] == "booked" and booked["booking_code"]
        results.append({"locale": locale, "quote": True, "receipt": True, "payment_idempotent": True})
        print(json.dumps(results[-1]), flush=True)
    phone = "synthetic-release-short"
    for index, text in enumerate(["Hi, I'd like to book a trip.", "Saturday", "2", "0", "none", "Ana Silva", "We will meet at the pier."]):
        turn(phone, text, index)
    fields = state_registry.wa_get_booking_state(phone)["fields"]["mermaid_intake"]
    assert fields["phase"] == "awaiting_summary_confirmation", fields
    assert [fields[key] for key in ("adults", "children", "infants")] == [2, 0, 0], fields
    Path("/app/data/canary-report.json").write_text(json.dumps({"results": results, "short_answers": True, "transcripts": transcripts}, ensure_ascii=False, indent=2))
    print(json.dumps({"passed": True, "locales": 6, "short_answers": True, "real_provider_sends": 0}), flush=True)


if __name__ == "__main__":
    main()
