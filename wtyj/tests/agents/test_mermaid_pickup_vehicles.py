"""Passenger-capacity and immutable transport-price integration checks."""
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from pypdf import PdfReader
from agents.marina import marina_agent
from agents.social import mermaid_reservation_store as store, mermaid_reservation_workflow as workflow
from agents.social import mermaid_documents as docs, mermaid_demo_payment as payment
from agents.social import mermaid_guest_experience as guest
from shared import config_loader, mermaid_catalog, state_registry


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    config = Path(__file__).resolve().parents[3] / 'clients/mermaid/config/client.json'
    monkeypatch.setattr(config_loader, '_CONFIG_PATH', str(config))
    monkeypatch.setattr(config_loader, '_cache', {})
    monkeypatch.setattr(state_registry, 'DB_PATH', str(tmp_path/'state.db'))
    monkeypatch.setattr(state_registry, '_alert_dispatcher', None)
    monkeypatch.setenv('MERMAID_DOCUMENT_ROOT', str(tmp_path/'documents'))
    monkeypatch.setenv('MERMAID_DEMO_SIGNING_SECRET', 'test-only')


def intake(**changes):
    return dict(dict(trip_date='2026-09-06', adults=4, children=1, infants=1,
                     customer_name='Test Guest', pickup_preference='pickup_requested',
                     pickup_location='Westpunt', language='en', phase='summary_confirmed'), **changes)


@pytest.mark.parametrize('adults,children,infants,vehicle,amount', [
    (1,0,0,'car',75), (5,0,0,'car',75), (2,2,1,'car',75),
    (6,0,0,'van',125), (5,1,0,'van',125), (4,1,1,'van',125), (9,0,0,'van',125),
])
def test_all_passengers_determine_vehicle_and_charge(adults, children, infants, vehicle, amount):
    fields=intake(adults=adults, children=children, infants=infants)
    item=store.confirm_reservation('guest',fields,idempotency_key='one')
    money=item['monetary_snapshot'];plan=money['pickup_plan']
    assert plan['passenger_count']==adults+children+infants
    assert plan['vehicle_key']==vehicle and plan['quantity']==1
    assert plan['vehicle_capacity'] >= plan['passenger_count']
    assert money['pickup_amount']==amount
    assert money['total']==adults*150+children*75+amount
    line=next(i for i in money['items'] if i['key']=='pickup')
    assert line['quantity']==1 and line['unit_amount']==line['line_total']==amount


@pytest.mark.parametrize('locale', workflow.SUPPORTED_LOCALES)
def test_van_price_and_capacity_match_every_customer_surface(locale,tmp_path):
    fields=intake(language=locale)
    item=store.confirm_reservation('guest',fields,idempotency_key='one')
    money=item['monetary_snapshot'];assert money['total']==800
    vehicle=guest.pickup_label(money,locale)
    for name,render in [
        ('quote',lambda p:docs.render_quote_pdf(item,p)),
        ('receipt',lambda p:docs.render_receipt_pdf(item,dict(currency='USD',amount=800,payment_reference='TEST',paid_at='2026-09-03T23:48:43+00:00'),p)),
    ]:
        target=tmp_path/f'{name}.pdf';render(target);pdf=PdfReader(target)
        assert len(pdf.pages)==1
        text=' '.join(pdf.pages[0].extract_text().split())
        assert vehicle in text and '125.00' in text and '800.00' in text and '05:45' in text
    summary=workflow._summary(fields,locale)
    assert vehicle in summary and '125.00' in summary and '800.00' in summary
    expires=int(time.time())+3600
    html=payment.checkout_page(item['public_id'],expires,payment.sign_payment(item['public_id'],expires,'test-only')).body.decode()
    assert vehicle in html and '125.00' in html and '800.00' in html


def test_party_correction_reprices_before_confirmation(monkeypatch):
    fields=intake(adults=5,children=0,infants=0,phase='awaiting_summary_confirmation')
    state_registry.wa_save_booking_state('guest',{'mermaid_intake':fields},{})
    model=Mock(return_value=dict(language='en',mermaid_action='details',fields={'adults':6},reply='Noted.',has_open_question=False))
    monkeypatch.setattr(marina_agent,'process_message',model)
    result=workflow.process_model_turn({'from':'guest','text':'One more adult, so six adults only','message_id':'six'},None)
    assert result.phase=='awaiting_summary_confirmation' and result.action is None
    assert 'USD 125.00' in result.text and 'USD 1,025.00' in result.text
    assert model.call_args.kwargs['thread_fields']['pickup_offer']['vehicle_key']=='car'
    assert store.latest_for_conversation('guest') is None


def test_missing_age_bands_do_not_finalize_vehicle_price():
    fields=intake();fields.pop('infants')
    money=store._money_snapshot(fields,mermaid_catalog.get_catalog())
    assert money['pickup_amount'] is None and money['pickup_plan']['status']=='awaiting_guest_count'
    assert not any(i['key']=='pickup' for i in money['items'])


def test_over_capacity_review_cannot_be_bypassed_by_model_or_store(monkeypatch):
    catalog=mermaid_catalog.get_catalog();catalog['pricing']['pickup_overflow']='team_review'
    monkeypatch.setattr(mermaid_catalog,'get_catalog',lambda:catalog)
    fields=intake(adults=10,children=0,infants=0)
    with pytest.raises(store.MermaidReservationError,match='pickup requires review'):
        store.confirm_reservation('guest',fields,idempotency_key='forbidden')
    fields['phase']='awaiting_summary_confirmation'
    state_registry.wa_save_booking_state('guest',{'mermaid_intake':fields},{})
    model=Mock(return_value=dict(language='en',mermaid_action='confirm_summary',fields={},reply='Confirmed at $75.',has_open_question=False))
    monkeypatch.setattr(marina_agent,'process_message',model)
    result=workflow.process_model_turn({'from':'guest','text':'yes','message_id':'yes'},None)
    assert result.action=='human_takeover' and '$75' not in result.text
    assert state_registry.get_active_escalation_mode('guest')=='soft'
    assert state_registry.get_ai_muted('guest') is False
    assert store.latest_for_conversation('guest') is None


@pytest.mark.parametrize('count,quantity,amount',[(10,2,250),(18,2,250),(19,3,375)])
def test_multiple_vans_only_when_explicitly_configured(count,quantity,amount,monkeypatch):
    catalog=mermaid_catalog.get_catalog();catalog['pricing']['pickup_overflow']='multiple_vans'
    monkeypatch.setattr(mermaid_catalog,'get_catalog',lambda:catalog)
    item=store.confirm_reservation('guest',intake(adults=count,children=0,infants=0),idempotency_key='one')
    plan=item['monetary_snapshot']['pickup_plan']
    assert plan['vehicle_key']=='van' and plan['quantity']==quantity
    assert plan['unit_amount']==125 and item['monetary_snapshot']['pickup_amount']==amount


def test_legacy_flat_fee_never_gains_a_vehicle_assignment(monkeypatch):
    old=mermaid_catalog.get_catalog();old['pricing'].pop('pickup_vehicles')
    old['pricing'].update(pickup_basis='per_booking',pickup_price=75)
    with monkeypatch.context() as m:
        m.setattr(mermaid_catalog,'get_catalog',lambda:old)
        item=store.confirm_reservation('legacy',intake(adults=6,children=0,infants=0),idempotency_key='old')
    money=item['monetary_snapshot']
    assert money['total']==975 and money['pickup_amount']==75
    text=guest.transport_text(item['intake'],'en',money)
    assert '75.00' in text and '125.00' not in text and 'up to' not in text
    assert guest.pickup_label(money,'en')==guest.guest_copy('en')['pickup_line']
    assert store.get_reservation(item['public_id'])==item


@pytest.mark.parametrize('vehicles', [None, [], [{'key':'car','capacity':0,'price':75},{'key':'van','capacity':9,'price':125}],
    [{'key':'car','capacity':5,'price':75},None,{'key':'van','capacity':9,'price':125}]])
def test_malformed_vehicle_configuration_fails_closed(vehicles):
    catalog=mermaid_catalog.get_catalog();catalog['pricing']['pickup_vehicles']=vehicles
    with pytest.raises(mermaid_catalog.MermaidCatalogError):mermaid_catalog.validate_catalog(catalog)
