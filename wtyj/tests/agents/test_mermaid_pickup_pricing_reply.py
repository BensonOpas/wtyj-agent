"""Pickup questions use every passenger and recorded amounts, never model math."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from agents.marina import marina_agent
from agents.social import mermaid_guest_experience as guest
from agents.social import mermaid_reservation_store as store
from agents.social import mermaid_reservation_workflow as workflow
from agents.social import mermaid_response_policy as policy
from shared import config_loader, mermaid_catalog, state_registry


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    config = Path(__file__).resolve().parents[3] / 'clients/mermaid/config/client.json'
    monkeypatch.setattr(config_loader, '_CONFIG_PATH', str(config))
    monkeypatch.setattr(config_loader, '_cache', {})
    monkeypatch.setattr(state_registry, 'DB_PATH', str(tmp_path/'state.db'))
    monkeypatch.setattr(state_registry, '_alert_dispatcher', None)
    monkeypatch.setattr(state_registry, '_summary_dispatcher', None)
    monkeypatch.setenv('MERMAID_DOCUMENT_ROOT', str(tmp_path/'documents'))


def intake(locale='en', **changes):
    return dict(dict(language=locale, phase='collecting', trip_date='2030-01-06',
                     adults=3, children=1, infants=1, customer_name='Dion Romer',
                     contact_phone='+12025550023'), **changes)


def model(monkeypatch, locale='en', **changes):
    output = dict(language=locale, mermaid_action='question', fields={},
                  reply='WRONG PICKUP: five people, all four fit, price 999.',
                  confidence='high', requires_human=False, has_open_question=True,
                  guest_question_excerpt='question', calendar_request='none',
                  status_request='pickup_pricing', security_event='none')
    output.update(changes)
    stub=Mock(return_value=output)
    monkeypatch.setattr(marina_agent, 'process_message', stub)
    return stub


def turn(monkeypatch, locale='en', saved_fields=None, reservation=None, **model_changes):
    if saved_fields is not None:
        state_registry.wa_save_booking_state('guest', {'mermaid_intake': saved_fields}, {})
    model(monkeypatch, locale, **model_changes)
    return workflow.process_model_turn({'from':'guest', 'message_id':'pickup', 'text':'question'}, reservation)


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
@pytest.mark.parametrize('adults,vehicle,capacity,amount', [(3,'car',5,75), (4,'van',9,125)])
def test_known_party_includes_infants_and_does_not_select_pickup(monkeypatch, locale, adults, vehicle, capacity, amount):
    fields=intake(locale, adults=adults)
    result=turn(monkeypatch, locale, fields)
    assert 'WRONG PICKUP' not in result.text
    assert guest.party_text(fields,locale) in result.text
    assert policy.copy('pickup_party_count',locale).format(count=adults+2) in result.text
    assert guest.guest_copy(locale)['pickup_'+vehicle].format(capacity=capacity) in result.text
    assert f'USD {amount:.2f}' in result.text and '05:45' in result.text
    assert policy.copy('pickup_round_trip',locale) in result.text
    saved=state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']
    assert 'pickup_preference' not in saved
    assert result.action is None and result.phase=='collecting'
    assert not store.latest_for_conversation('guest')


def test_original_pap_base023_turn3_replaces_contradictory_capacity(monkeypatch):
    fields=intake('pap')
    state_registry.wa_save_booking_state('guest',{'mermaid_intake':fields},{})
    # Recorded audit output, with only the new structured selector supplied.
    original='Pa un grupo di 5 persona, un auto tin kapasidat pa tur kuater i ta kosta USD 75 pa e auto, round-trip.'
    model(monkeypatch,'pap',reply=original, fields={'pickup_location':'Audit Hotel Alpha'},
          guest_question_excerpt='Kuantu e ta kosta pa buska nos na Audit Hotel Alpha?')
    result=workflow.process_model_turn({'from':'guest','message_id':'base023-turn3',
        'text':'Kuantu e ta kosta pa buska nos na Audit Hotel Alpha? Mi no a skohe pickup ainda.'},None)
    assert 'tur kuater' not in result.text
    assert guest.party_text(fields,'pap') in result.text
    assert policy.copy('pickup_party_count','pap').format(count=5) in result.text
    assert 'USD 75.00' in result.text and '05:45' in result.text
    saved=state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']
    assert saved['pickup_location']=='Audit Hotel Alpha' and 'pickup_preference' not in saved


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_unknown_party_offers_both_options_without_inventing_count(monkeypatch, locale):
    fields=intake(locale); fields.pop('infants')
    result=turn(monkeypatch, locale, fields)
    assert 'USD 75.00' in result.text and 'USD 125.00' in result.text
    assert policy.copy('pickup_need_party',locale) in result.text
    assert '05:45' in result.text and 'WRONG PICKUP' not in result.text
    assert 'infants' not in state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_existing_booking_without_pickup_does_not_gain_it(monkeypatch, locale):
    item=store.confirm_reservation('guest',intake(locale,pickup_preference='pier',phase='summary_confirmed'),idempotency_key='confirmed')
    for phase in ('quote_ready','demo_payment_pending'):
        item=store.transition(item['public_id'],phase,idempotency_key=phase,actor='test',reason='test')
    result=turn(monkeypatch,locale,reservation=item)
    assert policy.copy('pickup_not_included',locale) in result.text
    assert 'USD 75.00' in result.text and '05:45' in result.text
    assert store.get_reservation(item['public_id'])==item
    assert state_registry.get_active_escalation_mode('guest') is None


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_booked_pickup_uses_immutable_party_vehicle_and_price(monkeypatch, locale):
    fields=intake(locale,pickup_preference='pickup_requested',pickup_location='Test Hotel',phase='summary_confirmed')
    item=store.confirm_reservation('guest',fields,idempotency_key='confirmed')
    for phase in ('quote_ready','demo_payment_pending'):
        item=store.transition(item['public_id'],phase,idempotency_key=phase,actor='test',reason='test')
    item,_=store.complete_demo_payment(item['public_id'],payment_reference='SIMULATED',idempotency_key='paid')
    catalog=deepcopy(mermaid_catalog.get_catalog())
    catalog['pricing']['pickup_vehicles'][0].update(price=999,capacity=4)
    monkeypatch.setattr(mermaid_catalog,'get_catalog',lambda:deepcopy(catalog))
    result=turn(monkeypatch,locale,saved_fields=intake(locale,adults=8),reservation=item,
                fields={'adults':9})
    assert guest.party_text(item['intake'],locale) in result.text
    assert policy.copy('pickup_party_count',locale).format(count=5) in result.text
    assert guest.guest_copy(locale)['pickup_car'].format(capacity=5) in result.text
    assert 'USD 75.00' in result.text and '999' not in result.text and '125.00' not in result.text
    assert store.get_reservation(item['public_id'])==item


def test_mixed_question_keeps_distinct_faq_answer_and_explicit_pickup_choice(monkeypatch):
    result=turn(monkeypatch,saved_fields=intake(),other_question_reply='Breakfast is included.',
                fields={'pickup_preference':'pickup_requested','pickup_location':'Test Hotel'})
    assert result.text.endswith('Breakfast is included.') and 'USD 75.00' in result.text
    saved=state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']
    assert saved['pickup_preference']=='pickup_requested'
    assert result.phase=='collecting' and not store.latest_for_conversation('guest')


def test_ordinary_faq_is_not_replaced(monkeypatch):
    result=turn(monkeypatch,status_request='none',reply='Breakfast is included.')
    assert result.text=='Breakfast is included.'


def test_latest_draft_counts_replace_saved_pickup_offer(monkeypatch):
    result=turn(monkeypatch,saved_fields=intake(),fields={'adults':4})
    assert policy.copy('pickup_party_count','en').format(count=6) in result.text
    assert 'USD 125.00' in result.text and '75.00' not in result.text
    assert state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']['adults']==4


def test_legacy_recorded_amount_never_invents_vehicle_assignment(monkeypatch):
    old=deepcopy(mermaid_catalog.get_catalog())
    old['pricing'].pop('pickup_vehicles')
    old['pricing'].update(pickup_basis='per_booking',pickup_price=65)
    with monkeypatch.context() as m:
        m.setattr(mermaid_catalog,'get_catalog',lambda:deepcopy(old))
        item=store.confirm_reservation('guest',intake(adults=4,pickup_preference='pickup_requested',
              pickup_location='Test Hotel',phase='summary_confirmed'),idempotency_key='legacy')
    result=turn(monkeypatch,reservation=item)
    assert policy.copy('pickup_recorded_amount','en').format(currency='USD',amount='65.00') in result.text
    assert '75.00' not in result.text and '125.00' not in result.text
    assert store.get_reservation(item['public_id'])==item


def test_over_capacity_enquiry_does_not_guess_price_or_record_consent(monkeypatch):
    result=turn(monkeypatch,saved_fields=intake(adults=8))
    assert policy.copy('pickup_offer_review','en') in result.text
    assert 'USD' not in result.text and 'WRONG PICKUP' not in result.text
    saved=state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']
    assert 'pickup_preference' not in saved and state_registry.get_ai_muted('guest') is False


@pytest.mark.parametrize('action', ['confirm_summary','new_booking','cancel'])
def test_pending_review_decision_keeps_review_response(monkeypatch, action):
    state_registry.create_pending_notification('escalation','whatsapp','guest','Test Guest','Review','Review',mode='soft')
    result=turn(monkeypatch,saved_fields=intake(),mermaid_action=action)
    assert result.text==workflow.COPY['en']['human']
    assert result.phase=='human_takeover' and 'USD' not in result.text
    assert state_registry.get_active_escalation_mode('guest')=='soft'


@pytest.mark.parametrize('kind', ['human','security','cancel'])
def test_pickup_selector_cannot_replace_primary_action(monkeypatch, kind):
    changes = ({'mermaid_action':'request_human'} if kind=='human' else
               {'security_event':'blocked_override'} if kind=='security' else
               {'mermaid_action':'cancel'})
    result=turn(monkeypatch,saved_fields=intake(),**changes)
    assert 'USD' not in result.text and 'WRONG PICKUP' not in result.text
    if kind=='human':
        assert result.action=='human_takeover' and result.text==policy.copy('review_queued','en')
    elif kind=='security':
        assert result.text==policy.copy('security_blocked','en')
    else:
        assert result.action=='cancel' and result.text==''


@pytest.mark.parametrize('invalid', [[], {}, 3, True])
def test_malformed_other_answer_retries_same_event_without_caching(monkeypatch, invalid):
    from agents.social import mermaid_model_recovery as recovery
    monkeypatch.setattr(recovery.time,'time',lambda:10000.0)
    stub=model(monkeypatch,other_question_reply=invalid)
    fields=intake()
    state_registry.wa_save_booking_state('guest',{'mermaid_intake':fields},{})
    message={'from':'guest','message_id':'retry','text':'question'}
    first=workflow.process_model_turn(message,None)
    assert first.generation_failure['kind']=='invalid_response'
    assert state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']==fields
    retry_at=first.generation_failure['retry_at']
    monkeypatch.setattr(recovery.time,'time',lambda:retry_at+1)
    stub.return_value['other_question_reply']='Breakfast is included.'
    second=workflow.process_model_turn(message,None)
    assert second.generation_failure is None and second.text.endswith('Breakfast is included.')
    assert 'USD 75.00' in second.text and stub.call_count==2
