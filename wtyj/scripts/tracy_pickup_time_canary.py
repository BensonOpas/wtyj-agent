"""Isolated real-model pickup scheduling replay; no provider sends."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.social import mermaid_reservation_workflow as workflow
from agents.social import mermaid_demo_payment as payment
from agents.social import mermaid_reservation_store as store
from shared import config_loader, mermaid_catalog, state_registry


def main():
    assert os.environ.get('MERMAID_ISOLATED_CANARY') == 'synthetic-no-provider-send'
    assert Path('/app/data/.isolated-canary').is_file()
    assert not os.environ.get('LATE_API_KEY')
    assert config_loader.get_raw()['slug'] == 'mermaid'
    scheduled = mermaid_catalog.pickup_time()
    transcript = []

    def turn(phone, message):
        state_registry.dm_store_message(phone, 'whatsapp', 'user', message)
        reply = workflow.handle_demo_message(
            {'from': phone, 'text': message, 'message_id': f'{phone}-{len(transcript)}'},
            include_media=True, use_model=True,
        )
        state_registry.dm_store_message(phone, 'whatsapp', 'assistant', reply['text'])
        visible = reply['text'].split('https://')[0]
        transcript.append({'guest': message, 'tracy': visible})
        print(json.dumps(transcript[-1], ensure_ascii=False), flush=True)
        return reply

    phone = 'synthetic-pickup-time'
    intake = dict(trip_date='2026-09-06', adults=3, children=0, infants=0,
                  customer_name='Test Guest', contact_phone='+12025550123', pickup_preference='pickup_requested',
                  language='en', phase='collecting')
    state_registry.wa_save_booking_state(phone, {'mermaid_intake': intake}, {})
    state_registry.dm_store_message(phone, 'whatsapp', 'assistant', 'Would you like pickup?')
    first = turn(phone, 'Yes, please pick us up.')
    assert scheduled in first['text'] or '5:45' in first['text']
    assert not first.get('media')
    summary = turn(phone, 'Piscadera Bay Resort, Bungalow 342')
    assert scheduled in summary['text'] and 'USD 525.00' in summary['text']
    question = turn(phone, 'Is that 5:45 in the morning? And is the pickup price for all three of us?')
    assert 'Here is what I have' not in question['text']
    assert store.latest_for_conversation(phone) is None
    turn(phone, 'yes, looks right')
    item = store.latest_for_conversation(phone)
    assert item['state'] == 'demo_payment_pending'
    assert item['monetary_snapshot']['total'] == 525
    expires = int(time.time()) + 3600
    signature = payment.sign_payment(item['public_id'], expires, os.environ['MERMAID_DEMO_SIGNING_SECRET'])
    with patch.object(payment, 'send_reply', return_value=True) as sender, \
            patch.object(payment.icp_overrides, 'fetch_overrides_fresh', return_value={}), \
            patch.object(payment.icp_overrides, 'whatsapp_inbox_state', return_value=True), \
            patch.object(payment.icp_overrides, 'auto_reply_state', return_value=True):
        payment.complete_checkout(item['public_id'], expires, signature, 'success')
        sender.assert_called_once()
        assert scheduled in sender.call_args.args[3]
    before = store.get_reservation(item['public_id'])
    booked = turn(phone, 'What time do we need to be ready for pickup?')
    assert scheduled in booked['text'] or '5:45' in booked['text']
    assert store.get_reservation(item['public_id']) == before

    pier = dict(intake, pickup_preference='pier')
    state_registry.wa_save_booking_state('synthetic-pier-time', {'mermaid_intake': pier}, {})
    pier_reply = turn('synthetic-pier-time', "We're driving ourselves. What time should we arrive?")
    assert '06:45' in pier_reply['text'] or '6:45' in pier_reply['text']
    assert '5:45' not in pier_reply['text']
    enquiry = turn('synthetic-pickup-enquiry', 'How much is pickup from Westpunt and what time is it?')
    assert '75' in enquiry['text'] and '5:45' in enquiry['text']
    fields = state_registry.wa_get_booking_state('synthetic-pickup-enquiry')['fields']['mermaid_intake']
    assert fields.get('pickup_preference') != 'pickup_requested'
    print(json.dumps({'passed': True, 'model_turns': len(transcript), 'provider_sends': 0}), flush=True)


if __name__ == '__main__':
    main()
