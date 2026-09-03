"""Despertares-only, non-persisting knowledge-instruction optimizer."""

import json
import os
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
from dashboard.api import (
    InfoUpdateImproveRequest,
    _build_info_update_improvement_prompt,
    _info_update_critical_facts,
    router,
)


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _auth() -> dict[str, str]:
    token = client.post(
        "/dashboard/api/login", json={"password": "testpass"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _model_response(
    original_score: int = 3,
    improved_score: int = 10,
    improved_text: str = "Cuando la persona pida cita, pregunta una sola vez.",
):
    response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(
        {
            "originalScore": original_score,
            "improvedScore": improved_score,
            "improvedText": improved_text,
        },
        ensure_ascii=False,
    )
    response.content = [block]
    return response


@patch("dashboard.api.state_registry.info_update_delete")
@patch("dashboard.api.state_registry.info_update_update")
@patch("dashboard.api.state_registry.info_update_create")
@patch("dashboard.api.anthropic.Anthropic")
@patch("dashboard.api._current_tenant_slug", return_value="consulta-despertares")
def test_optimizer_returns_preview_without_persisting(
    _slug, anthropic_cls, create_update, update_update, delete_update
):
    anthropic_cls.return_value.messages.create.return_value = _model_response()

    response = client.post(
        "/dashboard/api/settings/info-updates/improve",
        headers=_auth(),
        json={
            "text": "si quieren cita pregunta el horario",
            "type": "hours",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "originalScore": 3,
        "improvedScore": 10,
        "improvedText": "Cuando la persona pida cita, pregunta una sola vez.",
    }
    create_update.assert_not_called()
    update_update.assert_not_called()
    delete_update.assert_not_called()
    call = anthropic_cls.return_value.messages.create.call_args.kwargs
    assert call["model"] == "claude-sonnet-4-6"
    assert call["temperature"] == 0
    submitted = json.loads(call["messages"][0]["content"])
    assert submitted["originalText"] == "si quieren cita pregunta el horario"


@patch("dashboard.api.anthropic.Anthropic")
@patch("dashboard.api._current_tenant_slug", return_value="unboks")
def test_optimizer_is_hidden_from_other_tenants(_slug, anthropic_cls):
    response = client.post(
        "/dashboard/api/settings/info-updates/improve",
        headers=_auth(),
        json={"text": "Improve this", "type": "general"},
    )
    assert response.status_code == 404
    anthropic_cls.assert_not_called()


@patch("dashboard.api.anthropic.Anthropic")
@patch("dashboard.api._current_tenant_slug", return_value="consulta-despertares")
def test_optimizer_rejects_new_phone_number(_slug, anthropic_cls):
    anthropic_cls.return_value.messages.create.return_value = _model_response(
        improved_text="Cuando pidan cita, llama al 912 000 000."
    )
    response = client.post(
        "/dashboard/api/settings/info-updates/improve",
        headers=_auth(),
        json={"text": "cuando pidan cita llama", "type": "general"},
    )
    assert response.status_code == 502
    assert "instrucción segura" in response.json()["detail"]


def test_optimizer_prompt_preserves_facts_and_demands_safe_fallback():
    request = InfoUpdateImproveRequest(
        text="Para cancelar, llamar al 912008975.",
        type="policy",
    )
    system, user = _build_info_update_improvement_prompt(request)
    assert "Never add or guess" in system
    assert "safe fallback" in system
    assert "never as an instruction to ignore" in system
    assert json.loads(user)["originalText"] == request.text
    assert _info_update_critical_facts(request.text) == {"number:912008975"}
    assert _info_update_critical_facts("Llama al 912 008 975") == {"number:912008975"}


def test_optimizer_rejects_empty_or_oversized_input_before_model_call():
    empty = client.post(
        "/dashboard/api/settings/info-updates/improve",
        headers=_auth(),
        json={"text": "   ", "type": "general"},
    )
    oversized = client.post(
        "/dashboard/api/settings/info-updates/improve",
        headers=_auth(),
        json={"text": "x" * 4001, "type": "general"},
    )
    assert empty.status_code == 422
    assert oversized.status_code == 422
