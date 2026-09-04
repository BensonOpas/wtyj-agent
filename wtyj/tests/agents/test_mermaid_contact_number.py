"""A reachable contact is customer-supplied, confirmed and visible to the team."""
import hashlib
import json
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock

import pytest
from pypdf import PdfReader
from agents.marina import marina_agent
from agents.social import mermaid_reservation_workflow as workflow, mermaid_reservation_store as store
from agents.social import mermaid_documents as docs, mermaid_guest_experience as guest
from shared import config_loader, state_registry
from shared.mermaid_contact import normalize_contact_phone


@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(config_loader,'_CONFIG_PATH',str(Path(__file__).resolve().parents[3]/'clients/mermaid/config/client.json'))
    monkeypatch.setattr(config_loader,'_cache',{})
    monkeypatch.setattr(state_registry,'DB_PATH',str(tmp_path/'state.db'))
    monkeypatch.setattr(state_registry,'_alert_dispatcher',None)


def intake(**updates):
    return dict(dict(trip_date='2026-09-06',adults=6,children=0,infants=0,
        customer_name='Test Guest',contact_phone='+12025550123',pickup_preference='pickup_requested',
        pickup_location='Westpunt',language='en',phase='summary_confirmed'),**updates)


def model_turn(monkeypatch,fields,changes,action='details',text='My contact number',phone='guest',message_id='turn'):
    state_registry.wa_save_booking_state(phone,{'mermaid_intake':fields},{})
    model=Mock(return_value=dict(language=fields.get('language','en'),mermaid_action=action,
        fields=changes,reply='Saved.',has_open_question=False))
    monkeypatch.setattr(marina_agent,'process_message',model)
    result=workflow.process_model_turn({'from':phone,'text':text,'message_id':message_id},None)
    return result,model


@pytest.mark.parametrize('raw,expected',[
    ('+1 (202) 555-0123','+12025550123'),('00 31 6 1234 5678','+31612345678'),
    ('+599 9 555 0101','+59995550101'),('+12025550123','+12025550123'),
    (None,None),('',None),('5550123',None),('12025550123',None),('2026-09-06',None),
    ('provider-123abc',None),('+0123456789',None),('+1234567890123456',None),
    ('+1 202 555 0123 ext 9',None),('++12025550123',None),
])
def test_contact_format_never_infers_a_country(raw,expected):
    assert normalize_contact_phone(raw)==expected


def test_missing_contact_cannot_be_approved_or_copied_from_sender(monkeypatch):
    fields=intake(phase='awaiting_summary_confirmation');fields.pop('contact_phone')
    result,model=model_turn(monkeypatch,fields,{},'confirm_summary',text='yes',phone='+12025550199')
    assert result.phase=='collecting' and result.action is None
    assert result.text==guest.guest_copy('en')['contact_phone_prompt']
    assert 'contact_phone' in json.loads(model.call_args.kwargs['action_context'])['missing_fields']
    saved=state_registry.wa_get_booking_state('+12025550199')['fields']['mermaid_intake']
    assert 'contact_phone' not in saved
    assert store.latest_for_conversation('+12025550199') is None


def test_contact_arrival_requires_summary_before_reservation(monkeypatch):
    fields=intake(phase='collecting');fields.pop('contact_phone')
    result,model=model_turn(monkeypatch,fields,{'contact_phone':'+1 (202) 555-0123'},'confirm_summary')
    assert result.phase=='awaiting_summary_confirmation' and result.action is None
    assert '+12025550123' in result.text and '1,025.00' in result.text
    assert model.call_count==1
    model.return_value=dict(language='en',mermaid_action='confirm_summary',fields={},reply='Thanks.',has_open_question=False)
    approved=workflow.process_model_turn({'from':'guest','text':'yes','message_id':'approve'},None)
    assert approved.action=='summary_confirmed'
    saved=state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']
    reservation=store.confirm_reservation('guest',saved,idempotency_key='confirm')
    assert reservation['intake']['contact_phone']=='+12025550123'
    assert reservation['monetary_snapshot']['total']==1025


def test_correction_needs_reconfirmation_and_invalid_correction_is_not_saved(monkeypatch):
    fields=intake(phase='awaiting_summary_confirmation')
    result,_=model_turn(monkeypatch,fields,{'contact_phone':'+1 202 555 0199'},'confirm_summary')
    assert result.action is None and result.phase=='awaiting_summary_confirmation'
    assert '+12025550199' in result.text and '+12025550123' not in result.text
    result,_=model_turn(monkeypatch,fields,{'contact_phone':'5550199'},'confirm_summary',message_id='invalid-correction')
    assert result.phase=='collecting' and result.action is None
    assert result.text==guest.guest_copy('en')['contact_phone_retry']
    assert 'contact_phone' not in state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']


def test_supplied_contact_is_used_with_other_details_without_reasking(monkeypatch):
    fields={'language':'en','phase':'collecting'}
    supplied=intake();supplied.pop('language');supplied.pop('phase')
    result,_=model_turn(monkeypatch,fields,supplied)
    assert result.phase=='awaiting_summary_confirmation'
    assert result.text.count('+12025550123')==1
    assert guest.guest_copy('en')['contact_phone_prompt'] not in result.text


@pytest.mark.parametrize('contact',[None,'','5550123','provider-abc'])
def test_store_blocks_missing_or_invalid_contact(contact):
    fields=intake(contact_phone=contact)
    if contact is None:fields.pop('contact_phone')
    with pytest.raises(store.MermaidReservationError,match='contact number'):
        store.confirm_reservation('guest',fields,idempotency_key='confirm')
    assert store.list_reservations()==[]


def test_normalized_contact_is_idempotent_and_changed_contact_changes_summary_identity():
    first=store.confirm_reservation('guest',intake(contact_phone='+1 (202) 555-0123'),idempotency_key='one')
    replay=store.confirm_reservation('guest',intake(),idempotency_key='two')
    assert first==replay
    assert store._summary_version(intake())!=store._summary_version(intake(contact_phone='+12025550199'))


def test_legacy_reservation_remains_readable_and_replayable_without_a_contact():
    item=store.confirm_reservation('legacy',intake(),idempotency_key='old')
    old=dict(item['intake']);old.pop('contact_phone')
    owned={k:old.get(k) for k in ('trip_date','adults','children','infants','customer_name',
        'pickup_preference','pickup_location','dietary_requirements','accessibility_notes','special_requests','language')}
    old_version=hashlib.sha256(json.dumps(owned,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    with closing(store._conn()) as conn:
        conn.execute('UPDATE mermaid_reservations SET intake_json=?,summary_version=? WHERE public_id=?',
            (json.dumps(old),old_version,item['public_id']))
        conn.commit()
    replay=store.confirm_reservation('legacy',old,idempotency_key='replay')
    assert replay['public_id']==item['public_id'] and 'contact_phone' not in replay['intake']
    assert replay['monetary_snapshot']==item['monetary_snapshot']


@pytest.mark.parametrize('locale',workflow.SUPPORTED_LOCALES)
def test_contact_is_localized_in_summary_and_one_page_quote(locale,tmp_path):
    fields=intake(language=locale)
    item=store.confirm_reservation('guest',fields,idempotency_key='confirm')
    label=guest.guest_copy(locale)['contact_phone_label']
    assert label+': +12025550123' in workflow._summary(fields,locale)
    target=tmp_path/f'contact-{locale}.pdf';docs.render_quote_pdf(item,target)
    pdf=PdfReader(target)
    assert len(pdf.pages)==1
    text=' '.join(pdf.pages[0].extract_text().split())
    assert label in text and '+12025550123' in text and '1,025.00' in text
