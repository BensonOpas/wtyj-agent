"""Regression scenarios from Calvin's real booking, without customer sends."""
from pathlib import Path
from unittest.mock import Mock
import pytest
from pypdf import PdfReader
from agents.marina import marina_agent
from agents.social import mermaid_reservation_workflow as workflow
from agents.social import mermaid_documents as docs, mermaid_demo_payment as payment
from agents.social import mermaid_reservation_store as store
from agents.social import mermaid_delivery_reconciliation as reconcile
from shared import config_loader, state_registry


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    config = Path(__file__).resolve().parents[3] / 'clients/mermaid/config/client.json'
    monkeypatch.setattr(config_loader, '_CONFIG_PATH', str(config))
    monkeypatch.setattr(config_loader, '_cache', {})
    monkeypatch.setattr(state_registry, 'DB_PATH', str(tmp_path/'state.db'))
    monkeypatch.setenv('MERMAID_DOCUMENT_ROOT', str(tmp_path/'documents'))
    monkeypatch.setenv('MERMAID_DEMO_SIGNING_SECRET', 'test-only')
    monkeypatch.setenv('UNBOKS_PUBLIC_BASE_URL', 'https://demo.example/api/mermaid')
    monkeypatch.setenv('LATE_API_KEY', 'test-only')


def fields(locale='en'):
    return dict(trip_date='2026-09-06', adults=3, children=0, infants=0,
                customer_name='Test Guest', pickup_preference='pickup_requested',
                pickup_location='Piscadera Bay Resort', language=locale, phase='summary_confirmed')


def test_mixed_price_question_is_answered_without_forcing_confirmation(monkeypatch):
    initial=fields(); initial.pop('pickup_location'); initial.pop('pickup_preference'); initial['phase']='collecting'
    state_registry.wa_save_booking_state('guest', {'mermaid_intake': initial}, {})
    answer="Pickup costs extra, but I don't have a confirmed price for your resort. Would you prefer to keep it pending?"
    model=Mock(return_value=dict(language='en', mermaid_action='details', has_open_question=True,
        fields={'pickup_preference':'pier','pickup_location':'Piscadera Bay Resort'}, reply=answer))
    monkeypatch.setattr(marina_agent, 'process_message', model)
    result=workflow.process_model_turn({'from':'guest','text':'We have a car. Does pickup cost extra?', 'message_id':'one'}, None)
    assert result.text==answer and result.phase=='collecting'
    assert model.call_args.kwargs['thread_fields']['authoritative_pricing']['total']==450
    assert not store.latest_for_conversation('guest')
    model.return_value=dict(language='en',mermaid_action='confirm_summary',has_open_question=True, fields={},reply='The price is still pending.')
    result=workflow.process_model_turn({'from':'guest','text':'yes but how much is pickup?', 'message_id':'two'},None)
    assert result.action is None


def test_one_summary_price_and_natural_approval(monkeypatch):
    initial=fields(); initial['phase']='collecting'
    state_registry.wa_save_booking_state('guest', {'mermaid_intake':initial},{})
    model=Mock(return_value=dict(language='en',mermaid_action='details',fields={},reply='Noted.',has_open_question=False))
    monkeypatch.setattr(marina_agent,'process_message',model)
    result=workflow.process_model_turn({'from':'guest','message_id':'summary','text':'Keep pickup pending'},None)
    assert result.text.count('Here is what I have')==1
    assert 'USD 450.00' in result.text and 'pickup excluded' in result.text
    assert 'Piscadera Bay Resort' in result.text and 'not confirmed' in result.text
    assert '0 children' not in result.text and '*YES*' not in result.text
    model.return_value=dict(language='en',mermaid_action='question',has_open_question=True,fields={},reply='Breakfast and lunch are included.')
    result=workflow.process_model_turn({'from':'guest','message_id':'question','text':'Is lunch included?'},None)
    assert result.text=='Breakfast and lunch are included.'
    model.return_value=dict(language='en',mermaid_action='confirm_summary',has_open_question=False,fields={},reply='Thanks.')
    result=workflow.process_model_turn({'from':'guest','message_id':'yes','text':'yesz'},None)
    assert result.action=='summary_confirmed'


@pytest.mark.parametrize('locale',workflow.SUPPORTED_LOCALES)
def test_pickup_is_consistent_in_quote_receipt_checkout_and_confirmation(locale, tmp_path):
    item=store.confirm_reservation('guest',fields(locale),idempotency_key='confirm',zernio_account_id='owned-account')
    record={'currency':'USD','amount':450,'payment_reference':'PAY-DEMO-test','paid_at':'2026-09-03T23:48:43+00:00'}
    quote=tmp_path/'quote.pdf'; receipt=tmp_path/'receipt.pdf'
    docs.render_quote_pdf(item,quote); docs.render_receipt_pdf(item,record,receipt)
    for p in (quote,receipt):
        text=' '.join(page.extract_text() for page in PdfReader(p).pages)
        assert 'Piscadera Bay Resort' in text and '450.00' in text
        assert '06:45' not in text
        assert item['catalog_version'] not in text
    text=payment.success_message(item,record)
    assert 'Piscadera Bay Resort' in text and '06:45' not in text
    import time
    expires=int(time.time())+3600
    signature=payment.sign_payment(item['public_id'],expires,'test-only')
    page=payment.checkout_page(item['public_id'],expires,signature).body.decode()
    assert 'Piscadera Bay Resort' in page
    if locale=='en':
        assert 'pickup excluded' in page and 'not confirmed' in page


def receipt_job():
    item=store.confirm_reservation('guest',fields(),idempotency_key='confirm',zernio_account_id='owned-account')
    doc,job=docs.create_receipt(item,{'currency':'USD','amount':450,'payment_reference':'DEMO','paid_at':'2026-09-03T23:48:43+00:00'})
    docs.mark_delivery(job['public_id'],False,'timeout')
    return doc,job


@pytest.mark.parametrize('status,expected',[('sent','pending'),('delivered','delivered'),('read','delivered'),('failed','failed')])
def test_late_delivery_matches_document_with_changed_signature_once(status, expected, monkeypatch):
    doc,job=receipt_job()
    message=dict(id='provider-123',direction='outgoing',deliveryStatus=status,message='Actual provider wording.',
        createdAt='2026-09-03T23:48:44Z',attachments=[{'url':f"https://demo.example/api/mermaid/api/public/mermaid-document/{doc['public_id']}?expires=old&signature=old"}])
    response=Mock(status_code=200);response.json.return_value={'messages':[message]}
    read=Mock(return_value=response)
    monkeypatch.setattr(reconcile.provider,'_provider_account_get',read)
    monkeypatch.setattr(reconcile.provider,'_provider_history_still_owned',lambda *a:True)
    assert reconcile.reconcile_job(job['public_id'])==expected
    reconcile.reconcile_job(job['public_id'])
    assert docs.delivery_job(job['public_id'])['status']==expected
    history=state_registry.dm_get_history('guest','whatsapp',limit=20)
    assert sum(m['text']=='Actual provider wording.' for m in history)==(1 if expected=='delivered' else 0)
    assert read.call_args.kwargs['params']['accountId']=='owned-account'


@pytest.mark.parametrize('mismatch',['host','document','ownership','incoming'])
def test_reconciliation_rejects_unrelated_or_no_longer_owned_evidence(mismatch,monkeypatch):
    doc,job=receipt_job()
    url=f"https://demo.example/api/mermaid/api/public/mermaid-document/{doc['public_id']}"
    if mismatch=='host':url=url.replace('demo.example','evil.example')
    if mismatch=='document':url+='-other'
    message=dict(id='provider-123',direction='incoming' if mismatch=='incoming' else 'outgoing',deliveryStatus='delivered',message='Wrong',attachments=[{'url':url}])
    response=Mock(status_code=200);response.json.return_value={'messages':[message]}
    monkeypatch.setattr(reconcile.provider,'_provider_account_get',lambda *a,**k:response)
    monkeypatch.setattr(reconcile.provider,'_provider_history_still_owned',lambda *a:mismatch!='ownership')
    assert reconcile.reconcile_job(job['public_id'])=='unknown'
    assert docs.delivery_job(job['public_id'])['status']=='pending'


def test_repeated_payment_callback_reconciles_instead_of_resending(monkeypatch):
    item=store.confirm_reservation('guest',fields(),idempotency_key='confirm',zernio_account_id='owned-account')
    for state in ['quote_ready','demo_payment_pending']:
        item=store.transition(item['public_id'],state,idempotency_key=state,actor='test',reason='test')
    sender=Mock(return_value=False);monkeypatch.setattr(payment,'send_reply',sender)
    monkeypatch.setattr(payment.icp_overrides,'fetch_overrides_fresh',lambda:{})
    monkeypatch.setattr(payment.icp_overrides,'whatsapp_inbox_state',lambda x:True)
    monkeypatch.setattr(payment.icp_overrides,'auto_reply_state',lambda x:True)
    monkeypatch.setattr(reconcile,'reconcile_job',lambda x:'pending')
    import time
    expires=int(time.time())+3600;signature=payment.sign_payment(item['public_id'],expires,'test-only')
    for _ in range(3):assert payment.complete_checkout(item['public_id'],expires,signature,'success').status_code==200
    sender.assert_called_once()
    conn=docs._conn()
    try:job=dict(conn.execute("SELECT * FROM mermaid_delivery_jobs WHERE kind='receipt'").fetchone())
    finally:conn.close()
    assert job['status']=='pending' and job['attempts']==1
    assert docs.claim_initial_delivery(job['public_id']) is False
