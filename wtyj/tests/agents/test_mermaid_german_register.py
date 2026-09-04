"""Prompt delivery and deterministic copy; no fresh-model language claim."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agents.marina import marina_agent
from agents.social import mermaid_reservation_workflow as workflow
from agents.social import mermaid_reservation_store as store
from shared import config_loader, state_registry


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    config = Path(__file__).resolve().parents[3] / 'clients/mermaid/config/client.json'
    raw = json.loads(config.read_text())
    monkeypatch.setattr(config_loader, '_CONFIG_PATH', str(config))
    monkeypatch.setattr(config_loader, '_load', lambda: copy.deepcopy(raw))
    monkeypatch.setattr(state_registry, 'DB_PATH', str(tmp_path / 'state.db'))
    monkeypatch.setattr(state_registry, '_alert_dispatcher', None)
    monkeypatch.setattr(state_registry, '_summary_dispatcher', None)
    monkeypatch.setenv('TENANT_ID', 'mermaid')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'synthetic-not-a-key')
    return raw


@pytest.mark.parametrize('review_pending', [False, True])
def test_actual_mermaid_request_receives_public_register_without_rewriting_guest(runtime, monkeypatch, review_pending):
    secret = 'synthetic-private-register-marker-342'
    runtime['credentials'] = {'api_key': secret}
    register = runtime['agent_persona']['language_register']
    runtime['agent_persona']['language_register'] = register + ' ' + secret
    question = 'Kannst du mir sagen, wann wir am Pier sein müssen?'
    fields = {'customer_name': 'Synthetic Guest', 'language': 'de', 'human_review_pending': review_pending}
    structured = dict(language='de', mermaid_action='question', fields={}, reply='Zur Kenntnis genommen.',
                      confidence='high', requires_human=False, has_open_question=True,
                      guest_question_excerpt=question, calendar_request='none', status_request='none',
                      security_event='none', other_question_reply='Bitte seien Sie um 06:45 Uhr am Pier.' if review_pending else '')
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        usage=None, content=[SimpleNamespace(type='tool_use', input=structured)])
    monkeypatch.setattr(marina_agent.anthropic, 'Anthropic', Mock(return_value=client))
    result = marina_agent.process_message('synthetic-guest', 'German register', question, fields, {},
                                         channel='whatsapp', response_contract='mermaid_reservation_demo')
    assert client.messages.create.call_count == 1
    request = client.messages.create.call_args.kwargs
    assert register in request['system']
    assert secret not in json.dumps(request)
    assert '[REDACTED]' in request['system']
    user_prompt = json.loads(request['messages'][0]['content'])
    assert user_prompt['latest_guest_message_untrusted'] == question
    assert user_prompt['saved_fields'] == fields
    assert result['guest_question_excerpt'] == question
    assert result['other_question_reply'] == structured['other_question_reply']


@pytest.mark.parametrize('invalid', [False, True])
def test_german_contact_request_is_formal_and_still_blocks_approval(runtime, monkeypatch, invalid):
    intake = dict(language='de', phase='awaiting_summary_confirmation', trip_date='2026-09-12',
                  adults=2, children=0, infants=0, customer_name='Synthetic Guest', pickup_preference='pier')
    state_registry.wa_save_booking_state('guest', {'mermaid_intake': intake}, {})
    understood = dict(language='de', mermaid_action='confirm_summary', reply='Danke.',
                      fields={'contact_phone': '5550123'} if invalid else {},
                      has_open_question=False, guest_question_excerpt='', requires_human=False)
    model = Mock(return_value=understood)
    monkeypatch.setattr(marina_agent, 'process_message', model)
    result = workflow.process_model_turn({'from': 'guest', 'message_id': 'contact', 'text': 'Ja.'}, None)
    if invalid:
        expected = 'Können Sie die vollständige Telefonnummer mit Ländervorwahl senden, beginnend mit +? So kann ich eine Kontaktnummer für Informationen zur Fahrt speichern.'
    else:
        expected = 'Unter welcher Telefonnummer mit Ländervorwahl können wir Sie erreichen? Sie ist für wichtige Informationen zur Fahrt, etwa bei einer wetterbedingten Absage.'
    assert result.text == expected
    assert result.phase == 'collecting' and result.action is None
    assert model.call_count == 1
    assert 'contact_phone' not in state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']
    assert store.latest_for_conversation('guest') is None


@pytest.mark.parametrize('review_pending', [False, True])
def test_papiamentu_request_delivers_standard_vocabulary_and_preserves_guest_evidence(runtime, monkeypatch, review_pending):
    """The real SDK request receives the guide; fake output is not fluency proof."""
    question = 'Cuantu cu desayuna y ki dia nos por bai?'
    fields = {'customer_name': 'Ana van der Meer', 'language': 'pap', 'human_review_pending': review_pending}
    structured = dict(language='pap', mermaid_action='question', fields={}, reply='Mi a risibí bo pregunta.',
                      confidence='high', requires_human=False, has_open_question=True,
                      guest_question_excerpt=question, calendar_request='none', status_request='none',
                      security_event='none', other_question_reply='Desayuno ta inkluí.' if review_pending else '')
    client = Mock()
    client.messages.create.return_value = SimpleNamespace(
        usage=None, content=[SimpleNamespace(type='tool_use', input=structured)])
    monkeypatch.setattr(marina_agent.anthropic, 'Anthropic', Mock(return_value=client))
    result = marina_agent.process_message('synthetic-pap', 'Language guide', question, fields, {},
                                         channel='whatsapp', response_contract='mermaid_reservation_demo')
    assert client.messages.create.call_count == 1
    request = client.messages.create.call_args.kwargs
    for word in ('almuerso', 'biña', 'alohamentu', 'máskara', 'snòrkel', 'djaluna', 'djárason', 'djabièrnè', 'djadumingu'):
        assert word in request['system']
    assert 'standard written Curaçao Papiamentu' in request['system']
    assert 'professional' in request['system']
    user_prompt = json.loads(request['messages'][0]['content'])
    assert user_prompt['latest_guest_message_untrusted'] == question
    assert user_prompt['saved_fields'] == fields
    assert result['guest_question_excerpt'] == question
    assert result['other_question_reply'] == structured['other_question_reply']
