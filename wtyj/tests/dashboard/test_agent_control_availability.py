"""Unavailable controls must not masquerade as Pause or stall tenant HTTP."""

import asyncio
import threading

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard import api
from shared import icp_overrides


def _app():
    app = FastAPI()
    app.include_router(api.router)

    @app.get("/probe")
    async def probe():
        return {"status": "ok"}

    return app


def _auth():
    return {"Authorization": f"Bearer {api._SESSION_TOKEN}"}


def _envelope(active):
    return {
        "available": True,
        "feature_toggles": {
            "ai_auto_reply": {"value": active, "source": "icp_override"},
        },
    }


@pytest.mark.parametrize("envelope", [
    {"available": False, "reason": "bridge unreachable", "feature_toggles": {}},
    {"available": False, "feature_toggles": {"ai_auto_reply": {"value": False}}},
    {"available": True, "feature_toggles": {}},
    _envelope(None),
])
def test_unverifiable_status_is_unavailable_without_pausing(monkeypatch, envelope):
    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    monkeypatch.setattr(icp_overrides, "fetch_overrides", lambda: envelope)

    def forbidden_write(*_args, **_kwargs):
        pytest.fail("A status read must never change agent controls")

    monkeypatch.setattr(icp_overrides, "set_auto_reply_enabled", forbidden_write)
    response = TestClient(_app()).get("/dashboard/api/agent/status", headers=_auth())
    assert response.status_code == 200
    assert response.json() == {
        "active": None, "status": "unavailable", "available": False,
        "source": "unavailable", "updatedAt": None,
    }


@pytest.mark.parametrize("active", [False, True])
def test_verified_status_recovers_after_unavailable_read(monkeypatch, active):
    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    states = iter([{"available": False}, _envelope(active)])
    monkeypatch.setattr(icp_overrides, "fetch_overrides", lambda: next(states))
    client = TestClient(_app())
    unavailable = client.get("/dashboard/api/agent/status", headers=_auth())
    verified = client.get("/dashboard/api/agent/status", headers=_auth())
    assert unavailable.json()["status"] == "unavailable"
    assert verified.json()["active"] is active
    assert verified.json()["status"] == ("active" if active else "paused")
    assert verified.json()["available"] is True


@pytest.mark.parametrize("method,path", [
    ("GET", "/agent/status"),
    ("PUT", "/agent/status"),
    ("GET", "/icp-overrides"),
    ("GET", "/onboarding/status"),
])
def test_control_bridge_wait_does_not_block_other_http(monkeypatch, method, path):
    bridge_started = threading.Event()
    bridge_release = threading.Event()

    def held_bridge(*_args):
        bridge_started.set()
        bridge_release.wait(timeout=5)
        return _envelope(True)

    monkeypatch.setattr(icp_overrides, "fetch_overrides", held_bridge)
    monkeypatch.setattr(icp_overrides, "set_auto_reply_enabled", held_bridge)

    async def exercise():
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://tenant.test") as client:
            kwargs = {"json": {"active": True}} if method == "PUT" else {}
            control = asyncio.create_task(client.request(
                method, f"/dashboard/api{path}", headers=_auth(), **kwargs,
            ))
            try:
                assert await asyncio.to_thread(bridge_started.wait, 5)
                assert not control.done(), "Control bridge blocked the event loop until timeout"
                probe = await asyncio.wait_for(client.get("/probe"), timeout=2)
                assert probe.status_code == 200
                assert probe.json() == {"status": "ok"}
                assert not control.done(), "Other routes must respond before the control bridge"
            finally:
                bridge_release.set()
                completed = await asyncio.wait_for(control, timeout=5)
            assert completed.status_code == 200

    asyncio.run(exercise())


@pytest.mark.parametrize("first_path", ["agent/status", "icp-overrides"])
def test_parallel_healthy_dashboard_reads_keep_agent_available(monkeypatch, first_path):
    monkeypatch.setenv("TENANT_ID", "demo")
    monkeypatch.setenv("TENANT_RUNTIME_CONTROLS_REQUIRED", "true")
    monkeypatch.setenv("NR3_INTERNAL_OVERRIDES_URL", "http://bridge.test")
    monkeypatch.setenv("NR3_INTERNAL_API_TOKEN", "local-test-token")
    icp_overrides.clear_cache()
    first_started = threading.Event()
    first_release = threading.Event()
    second_fetch_entered = threading.Event()
    second_bridge_started = threading.Event()
    calls = []
    fetch_calls = []
    envelope = {"tenant_id": "demo", **_envelope(True)}
    fetch_overrides = icp_overrides.fetch_overrides

    def observed_fetch():
        fetch_calls.append(1)
        if len(fetch_calls) == 2:
            second_fetch_entered.set()
        return fetch_overrides()

    def controlled_get(*_args, **_kwargs):
        calls.append(1)
        if len(calls) == 1:
            first_started.set()
            assert first_release.wait(timeout=5)
        else:
            second_bridge_started.set()
        return httpx.Response(200, json=envelope)

    monkeypatch.setattr(icp_overrides.requests, "get", controlled_get)
    monkeypatch.setattr(icp_overrides, "fetch_overrides", observed_fetch)

    async def exercise():
        app = _app()
        companion_started = asyncio.Event()
        companion_path = "icp-overrides" if first_path == "agent/status" else "agent/status"

        async def observed_app(scope, receive, send):
            if scope.get("path") == f"/dashboard/api/{companion_path}":
                companion_started.set()
            await app(scope, receive, send)

        transport = httpx.ASGITransport(app=observed_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://tenant.test") as client:
            first = asyncio.create_task(client.get(
                f"/dashboard/api/{first_path}", headers=_auth(),
            ))
            companion = None
            try:
                assert await asyncio.to_thread(first_started.wait, 5)
                companion = asyncio.create_task(client.get(
                    f"/dashboard/api/{companion_path}", headers=_auth(),
                ))
                await asyncio.wait_for(companion_started.wait(), timeout=2)
                assert await asyncio.to_thread(second_fetch_entered.wait, 5)
                # Give the second worker a bounded chance to reveal a duplicate
                # bridge GET while the first is held. A coalesced read waits.
                assert not await asyncio.to_thread(second_bridge_started.wait, 0.25)
                assert not first.done()
            finally:
                first_release.set()
                first_response = await asyncio.wait_for(first, timeout=5)
                if companion is not None:
                    companion_response = await asyncio.wait_for(companion, timeout=5)
            assert first_response.status_code == companion_response.status_code == 200
            assert first_response.json()["available"] is True
            assert companion_response.json()["available"] is True
            agent = first_response if first_path == "agent/status" else companion_response
            assert agent.json()["active"] is True
            assert agent.json()["status"] == "active"

    try:
        asyncio.run(exercise())
        assert len(calls) == 1
    finally:
        icp_overrides.clear_cache()
