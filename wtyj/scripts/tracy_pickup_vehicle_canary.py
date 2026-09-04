"""Real-model pickup vehicle replay in disposable data; no provider sends."""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.social import mermaid_reservation_workflow as workflow
from agents.social import mermaid_reservation_store as store
from shared import config_loader, mermaid_catalog, state_registry


def main():
    assert os.environ.get('MERMAID_ISOLATED_CANARY') == 'synthetic-no-provider-send'
    assert Path('/app/data/.isolated-canary').is_file()
    assert not os.environ.get('LATE_API_KEY')
    assert config_loader.get_raw()['slug'] == 'mermaid'
    turns = []

    def turn(phone, message):
        state_registry.dm_store_message(phone, 'whatsapp', 'user', message)
        reply = workflow.handle_demo_message(
            {'from': phone, 'text': message, 'message_id': f'{phone}-{len(turns)}'},
            include_media=True, use_model=True,
        )
        state_registry.dm_store_message(phone, 'whatsapp', 'assistant', reply['text'])
        turns.append({'guest': message, 'tracy': reply['text'].split('https://')[0]})
        print(json.dumps(turns[-1], ensure_ascii=False), flush=True)
        return reply

    options = turn('synthetic-vehicle-options', 'Hi, how much is pickup from Westpunt?')
    assert '75' in options['text'] and '125' in options['text']
    assert '5' in options['text'] and '9' in options['text']
    assert state_registry.wa_get_booking_state('synthetic-vehicle-options')['fields']['mermaid_intake'].get('pickup_preference') != 'pickup_requested'
    car = turn('synthetic-vehicle-five', 'How much is pickup for five adults only?')
    assert '75' in car['text'] and 'car' in car['text'].lower()
    baby = turn('synthetic-vehicle-baby', 'We are five adults and one baby. Can we use the $75 pickup car?')
    assert '125' in baby['text'] and 'van' in baby['text'].lower()
    nine = turn('synthetic-vehicle-nine', 'How much is pickup for nine adults only?')
    assert '125' in nine['text'] and 'van' in nine['text'].lower()

    phone = 'synthetic-vehicle-correction'
    fields = dict(trip_date='2026-09-06', adults=5, children=0, infants=0, customer_name='Test Guest',
                  contact_phone='+12025550123', pickup_preference='pickup_requested', pickup_location='Westpunt', language='en',
                  phase='awaiting_summary_confirmation')
    state_registry.wa_save_booking_state(phone, {'mermaid_intake': fields}, {})
    state_registry.dm_store_message(phone, 'whatsapp', 'assistant', workflow._summary(fields, 'en'))
    changed = turn(phone, 'Actually six adults only. Is pickup still $75?')
    assert '125' in changed['text'] and 'van' in changed['text'].lower()
    assert 'name' not in changed['text'].lower(), 'The known reservation name must not be requested again'
    assert not changed.get('media') and store.latest_for_conversation(phone) is None
    summary = turn(phone, 'Okay, update it to six adults.')
    assert '125.00' in summary['text'] and '1,025.00' in summary['text']
    quoted = turn(phone, 'yes, looks right')
    item = store.latest_for_conversation(phone)
    assert quoted.get('media') and item['state'] == 'demo_payment_pending'
    plan = item['monetary_snapshot']['pickup_plan']
    assert plan['vehicle_key'] == 'van' and plan['quantity'] == 1
    assert item['monetary_snapshot']['total'] == 1025 and plan['amount'] == 125

    large = turn('synthetic-vehicle-ten', 'Please arrange pickup for ten adults only from Westpunt.')
    if mermaid_catalog.get_catalog()['pricing']['pickup_overflow'] == 'team_review':
        assert state_registry.get_active_escalation_mode('synthetic-vehicle-ten') == 'soft'
        assert state_registry.get_ai_muted('synthetic-vehicle-ten') is False
    else:
        assert '250' in large['text'] and 'van' in large['text'].lower()
    assert store.latest_for_conversation('synthetic-vehicle-ten') is None
    print(json.dumps({'passed': True, 'model_turns': len(turns), 'provider_sends': 0}), flush=True)


if __name__ == '__main__':
    main()
