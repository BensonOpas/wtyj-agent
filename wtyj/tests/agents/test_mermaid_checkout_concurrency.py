"""Receipt delivery must leave the webhook server available to fetch its PDF."""

import asyncio
from pathlib import Path
import threading

import httpx

from agents.social import (
    mermaid_demo_payment,
    mermaid_documents,
    mermaid_reservation_store,
    webhook_server,
)
from shared import config_loader, state_registry


def test_checkout_keeps_health_and_signed_receipt_available(monkeypatch, tmp_path):
    config = Path(__file__).resolve().parents[3] / "clients/mermaid/config/client.json"
    monkeypatch.setattr(config_loader, "_CONFIG_PATH", str(config))
    monkeypatch.setattr(config_loader, "_cache", {})
    monkeypatch.setattr(state_registry, "DB_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("MERMAID_DOCUMENT_ROOT", str(tmp_path / "documents"))
    monkeypatch.setenv("MERMAID_DEMO_SIGNING_SECRET", "checkout-test-secret")
    monkeypatch.setenv("UNBOKS_PUBLIC_BASE_URL", "https://mermaid.test")
    monkeypatch.setattr(
        mermaid_demo_payment.icp_overrides,
        "fetch_overrides_fresh",
        lambda: {
            "available": True,
            "feature_toggles": {
                "ai_auto_reply": {"value": True},
                "whatsapp_inbox": {"value": True},
            },
        },
    )
    reservation = mermaid_reservation_store.confirm_reservation(
        "checkout-concurrency-guest",
        {
            "trip_date": "2026-09-05", "adults": 2, "children": 0, "infants": 0,
            "customer_name": "Test Guest", "pickup_preference": "pier",
            "language": "en", "phase": "summary_confirmed",
        },
        idempotency_key="checkout-concurrency-confirm",
        zernio_account_id="test-account",
    )
    for state in ("quote_ready", "demo_payment_pending"):
        reservation = mermaid_reservation_store.transition(
            reservation["public_id"], state,
            idempotency_key=f"checkout-concurrency:{state}",
            actor="system", reason="Concurrency regression setup",
        )
    payment_url = mermaid_demo_payment.build_payment_url(
        "https://mermaid.test", reservation["public_id"], "checkout-test-secret",
    )
    provider_started = threading.Event()
    provider_release = threading.Event()
    receipt_urls = []
    worker_submissions = []
    run_in_threadpool = webhook_server.run_in_threadpool

    async def observed_threadpool(function, *args, **kwargs):
        worker_submissions.append(function)
        return await run_in_threadpool(function, *args, **kwargs)

    monkeypatch.setattr(webhook_server, "run_in_threadpool", observed_threadpool)

    def held_provider_send(*_args, **kwargs):
        receipt_urls.append(kwargs["attachment_url"])
        provider_started.set()
        # This bound only prevents a broken implementation hanging the suite.
        # Success is event-driven: the test releases delivery after both GETs.
        return provider_release.wait(timeout=5)

    monkeypatch.setattr(mermaid_demo_payment, "send_reply", held_provider_send)

    async def exercise_routes():
        second_request_started = asyncio.Event()
        checkout_requests = 0

        async def observed_app(scope, receive, send):
            nonlocal checkout_requests
            if scope["type"] == "http" and scope["method"] == "POST":
                checkout_requests += 1
                if checkout_requests == 2:
                    second_request_started.set()
            await webhook_server.app(scope, receive, send)

        transport = httpx.ASGITransport(app=observed_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://mermaid.test",
        ) as client:
            checkout = asyncio.create_task(client.post(payment_url, data={"status": "success"}))
            replay = None
            try:
                assert await asyncio.to_thread(provider_started.wait, 5)
                assert not checkout.done(), "Checkout blocked the event loop until delivery timed out"
                replay = asyncio.create_task(client.post(payment_url, data={"status": "success"}))
                await asyncio.wait_for(second_request_started.wait(), timeout=2)
                assert len(worker_submissions) == 1, "Duplicate checkout must queue before occupying a worker"
                health, head, document = await asyncio.wait_for(
                    asyncio.gather(
                        client.get("/health"),
                        client.head("/health"),
                        client.get(receipt_urls[0]),
                    ),
                    timeout=2,
                )
                assert health.status_code == head.status_code == 200
                assert health.json() == {"status": "ok"}
                assert document.status_code == 200
                assert document.headers["content-type"] == "application/pdf"
                assert document.content.startswith(b"%PDF-")
                assert not checkout.done(), "Receipt fetch must finish before provider delivery"
                assert not replay.done(), "The duplicate checkout must wait for the first delivery"
            finally:
                provider_release.set()
                completed = await asyncio.wait_for(checkout, timeout=5)
                if replay is not None:
                    replayed = await asyncio.wait_for(replay, timeout=5)
            assert completed.status_code == 200
            assert "Demo payment complete" in completed.text
            assert replayed.status_code == 200
            assert "Demo payment complete" in replayed.text

    asyncio.run(exercise_routes())
    documents = mermaid_documents.documents_for_reservation(reservation["public_id"])
    assert len(receipt_urls) == 1
    assert len(worker_submissions) == 2
    assert documents[0]["delivery_status"] == "delivered"
