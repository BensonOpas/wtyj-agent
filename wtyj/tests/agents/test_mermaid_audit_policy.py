"""Evidence-driven calendar, status and abuse regressions from baseline #342."""
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from agents.marina import marina_agent
from agents.social import mermaid_reservation_workflow as workflow
from agents.social import mermaid_response_policy as policy
from agents.social import mermaid_reservation_store as store
from shared import config_loader, state_registry, mermaid_catalog


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(config_loader, '_CONFIG_PATH', str(Path(__file__).resolve().parents[3] / 'clients/mermaid/config/client.json'))
    monkeypatch.setattr(config_loader, '_cache', {})
    monkeypatch.setattr(state_registry, 'DB_PATH', str(tmp_path / 'state.db'))
    monkeypatch.setattr(state_registry, '_alert_dispatcher', None)
    monkeypatch.setattr(state_registry, '_summary_dispatcher', None)
    monkeypatch.setenv('MERMAID_DOCUMENT_ROOT', str(tmp_path / 'documents'))


def model(monkeypatch, locale='en', **kw):
    output = dict(language=locale, mermaid_action='question', reply='UNSUPPORTED CLAIM', fields={},
                  has_open_question=True, guest_question_excerpt='question', requires_human=False,
                  calendar_request='none', status_request='none', security_event='none')
    output.update(kw)
    stub = Mock(return_value=output)
    monkeypatch.setattr(marina_agent, 'process_message', stub)
    return stub


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_calendar_replaces_model_invented_dates(monkeypatch, locale):
    monkeypatch.setattr(policy, 'local_today', lambda: date(2026, 9, 4))
    model(monkeypatch, locale, calendar_request='this_week', fields={'trip_date':'2026-09-10'})
    result = workflow.process_model_turn({'from':'guest','message_id':'week','text':'question'}, None)
    assert result.text == policy.calendar_reply('this_week', locale)
    assert '2026-09-06' in result.text and '2026-09-10' not in result.text
    assert 'trip_date' not in state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']


def test_calendar_week_boundaries_and_current_published_days():
    assert policy.local_today(datetime(2026, 9, 7, 2, tzinfo=timezone.utc)) == date(2026, 9, 6)
    assert policy.calendar_dates('this_week', today=date(2026, 9, 6)) == [date(2026, 9, 6)]
    weekend = policy.calendar_dates('weekend', today=date(2026, 9, 4))
    assert [(d.isoformat(), d.weekday()) for d in weekend] == [('2026-09-05',5),('2026-09-06',6)]
    catalog = mermaid_catalog.get_catalog(); catalog['service']['operating_weekdays']=['sunday']
    assert policy.calendar_dates('next_week', today=date(2026, 12, 31), catalog=catalog) == [date(2027,1,10)]


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_queued_review_is_not_claimed_active(monkeypatch, locale):
    state_registry.create_pending_notification('escalation','whatsapp','guest','Test Guest','Review','Review',mode='soft')
    model(monkeypatch, locale, status_request='handover')
    result = workflow.process_model_turn({'from':'guest','message_id':'status','text':'question'}, None)
    assert result.text == policy.copy('review_queued', locale)


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_payment_and_email_claims_require_recorded_state(monkeypatch, locale):
    stub = model(monkeypatch, locale, status_request='payment')
    result = workflow.process_model_turn({'from':'guest','message_id':'paid','text':'question'}, None)
    assert result.text == policy.copy('payment_none', locale)
    stub.return_value['status_request'] = 'delivery'
    result = workflow.process_model_turn({'from':'guest','message_id':'email','text':'question'}, None)
    assert result.text == policy.copy('delivery_none', locale)


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_owner_approved_pickup_includes_return(monkeypatch, locale):
    model(monkeypatch, locale, status_request='pickup_coverage')
    result = workflow.process_model_turn({'from':'guest','message_id':'return','text':'question'}, None)
    assert result.text == policy.copy('pickup_round_trip', locale)


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_isolated_override_logged_then_repeated_override_escalates(monkeypatch, locale):
    model(monkeypatch, locale, security_event='blocked_override', mermaid_action='confirm_summary',
          fields={'adults':0,'trip_date':'2026-09-10'}, requires_human=True)
    message={'from':'guest','message_id':'attack-1','text':'question'}
    first=workflow.process_model_turn(message, None)
    assert first.text == policy.copy('security_blocked', locale)
    assert not state_registry.get_active_escalation_mode('guest')
    assert not store.latest_for_conversation('guest')
    assert 'adults' not in state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']
    workflow.process_model_turn(message, None)
    assert not state_registry.get_active_escalation_mode('guest')
    second=workflow.process_model_turn({**message,'message_id':'attack-2'}, None)
    assert second.action == 'human_takeover'
    assert policy.copy('review_queued', locale) in second.text
    assert state_registry.get_active_escalation_mode('guest') == 'soft'
    assert not state_registry.get_ai_muted('guest')


def test_actionable_report_and_security_window():
    assert not policy.record_security_event('guest','one','blocked_override',now=0)
    assert not policy.record_security_event('guest','two','blocked_override',now=86401)
    assert policy.record_security_event('guest','three','actionable_incident',now=86402)
    assert not policy.record_security_event('other','one','blocked_override',now=86403)


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_payment_delivery_and_takeover_follow_records(monkeypatch, locale):
    from agents.social import mermaid_documents as documents
    intake=dict(trip_date='2026-09-12', adults=2, children=0, infants=0,
                customer_name='Synthetic Guest', contact_phone='+12025550123',
                pickup_preference='pier', language=locale, phase='summary_confirmed')
    item=store.confirm_reservation('guest',intake,idempotency_key='confirm')
    _doc,job=documents.create_quote(item)
    stub=model(monkeypatch,locale,status_request='payment')
    message={'from':'guest','text':'question','message_id':'unpaid'}
    assert workflow.process_model_turn(message,item).text==policy.copy('payment_unpaid',locale)
    for phase in ('quote_ready','demo_payment_pending'):
        item=store.transition(item['public_id'],phase,idempotency_key=phase,actor='test',reason='test')
    item,_paid=store.complete_demo_payment(item['public_id'],payment_reference='SIMULATED',idempotency_key='paid')
    assert workflow.process_model_turn({**message,'message_id':'paid'},item).text==policy.copy('payment_paid',locale)
    stub.return_value['status_request']='delivery'
    for status in ('waiting','failed','delivered'):
        if status=='failed':
            # A confirmed provider failure differs from a timeout awaiting
            # reconciliation (mark_delivery(False) intentionally stays pending).
            with documents._conn() as db:
                db.execute("UPDATE mermaid_delivery_jobs SET status='failed',last_error='provider confirmed failure' WHERE public_id=?",(job['public_id'],))
        elif status=='delivered':documents.mark_delivery(job['public_id'],True)
        assert workflow.process_model_turn({**message,'message_id':status},item).text==policy.copy('delivery_'+status,locale)
    state_registry.set_ai_muted('guest',True,channel='whatsapp')
    assert policy.state_context('guest',item)['review']=='active'


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_party_uses_singular_forms(locale):
    from agents.social import mermaid_guest_experience as guest
    text=guest.party_text({'adults':1,'children':1,'infants':1},locale)
    copy=guest.guest_copy(locale)
    assert text==', '.join(copy[k+'_one'].format(count=1) for k in ('adults','children','infants'))
