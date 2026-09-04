"""Real-model audit replay in a disposable container; never sends messages."""
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents.social import mermaid_reservation_workflow as workflow
from agents.social import mermaid_demo_payment as payment, mermaid_documents as documents
from agents.social import mermaid_reservation_store as reservations
from shared import config_loader, state_registry
from agents.marina import marina_agent
from shared.public_business_config import _secret_values


def main():
    if os.environ.get('MERMAID_ISOLATED_CANARY') != 'synthetic-no-provider-send' or not Path('/app/data/.isolated-canary').is_file():
        raise RuntimeError('Disposable data and explicit canary marker required')
    assert config_loader.get_raw().get('slug') == 'mermaid'
    secrets = _secret_values(config_loader.get_raw())
    original = marina_agent.anthropic.Anthropic
    def guarded(**kwargs):
        client=original(**kwargs); create=client.messages.create
        def call(**payload):
            raw=json.dumps(payload)
            assert not any(s in raw for s in secrets)
            return create(**payload)
        client.messages.create=call
        return client
    marina_agent.anthropic.Anthropic=guarded
    phone='synthetic-tracy-ux'
    transcript=[]
    turns=[
        "Hi, I wanna book for Sunday 6 September 2026, two adults and our 16 year old son. My name is Calvin Adamus.",
        "We have a rental car, we can make it. Is there any cost for picking us up? We're at Piscadera Bay Resort.",
        "I'd like pickup from Piscadera Bay Resort, please.",
        "Will that pickup price be included in the PDF?",
        "yesz",
    ]
    for i,text in enumerate(turns):
        state_registry.dm_store_message(phone,'whatsapp','user',text)
        reply=workflow.handle_demo_message({'from':phone,'text':text,'message_id':f'ux-{i}','from_name':'Test'},include_media=True,use_model=True)
        state_registry.dm_store_message(phone,'whatsapp','assistant',reply['text'])
        print(json.dumps({'saved':state_registry.wa_get_booking_state(phone)['fields']['mermaid_intake']},ensure_ascii=False),flush=True)
        if i in (1,3):
            assert '*Here is what I have*' not in reply['text'], reply
            assert reservations.latest_for_conversation(phone) is None
        if i==2:
            assert 'USD 450.00' in reply['text'] and 'pickup excluded' in reply['text'], reply
        if i<4:assert reply.get('media') is None
        visible=reply['text'].split('https://')[0]
        transcript.append({'guest':text,'tracy':visible})
        print(json.dumps(transcript[-1],ensure_ascii=False),flush=True)
    item=reservations.latest_for_conversation(phone)
    assert item['state']=='demo_payment_pending'
    assert item['intake']['pickup_location']=='Piscadera Bay Resort'
    assert item['monetary_snapshot']['total']==450
    import time
    expires=int(time.time())+3600;signature=payment.sign_payment(item['public_id'],expires,os.environ['MERMAID_DEMO_SIGNING_SECRET'])
    with patch.object(payment,'send_reply',return_value=True) as sender, patch.object(payment.icp_overrides,'fetch_overrides_fresh',return_value={}), patch.object(payment.icp_overrides,'whatsapp_inbox_state',return_value=True), patch.object(payment.icp_overrides,'auto_reply_state',return_value=True):
        payment.complete_checkout(item['public_id'],expires,signature,'success')
        payment.complete_checkout(item['public_id'],expires,signature,'success')
        sender.assert_called_once()
        assert 'Piscadera Bay Resort' in sender.call_args.args[3]
        assert '06:45' not in sender.call_args.args[3]
        print(json.dumps({'confirmation':sender.call_args.args[3]},ensure_ascii=False),flush=True)
    Path('/app/data/ux-canary.json').write_text(json.dumps(transcript,ensure_ascii=False,indent=2))
    print(json.dumps({'passed':True,'model_turns':len(turns),'provider_sends':0}),flush=True)

if __name__=='__main__':main()
