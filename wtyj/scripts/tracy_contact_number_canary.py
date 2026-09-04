"""Isolated real-model contact-number journey; no customer messages."""
import json
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.social import mermaid_reservation_workflow as workflow,mermaid_reservation_store as store
from shared import state_registry

assert os.environ.get('MERMAID_ISOLATED_CANARY')=='synthetic-no-provider-send'
assert Path('/app/data/.isolated-canary').is_file()
assert not os.environ.get('LATE_API_KEY')
turns=[]

def turn(phone,text):
    state_registry.dm_store_message(phone,'whatsapp','user',text)
    result=workflow.handle_demo_message({'from':phone,'text':text,'message_id':str(len(turns))},include_media=True,use_model=True)
    state_registry.dm_store_message(phone,'whatsapp','assistant',result['text'])
    saved=state_registry.wa_get_booking_state(phone)['fields']['mermaid_intake']
    evidence=dict(guest=text,tracy=result['text'].split('https://')[0],phase=saved['phase'],contact=saved.get('contact_phone'))
    turns.append(evidence);print(json.dumps(evidence,ensure_ascii=False),flush=True)
    return result,saved

phone='synthetic-contact-step'
r,s=turn(phone,"I'd like to book Sunday 6 September 2026 for two adults only. My name is Test Guest and we'll meet you at the pier.")
assert s['customer_name']=='Test Guest' and s['adults']==2
assert s['phase']=='collecting' and not s.get('contact_phone') and not r.get('media')
assert 'number' in r['text'].lower() and ('weather' in r['text'].lower() or 'update' in r['text'].lower())
r,s=turn(phone,'Just use this WhatsApp number.')
assert not s.get('contact_phone') and not r.get('media')
r,s=turn(phone,'+1 (202) 555-0123')
assert s['contact_phone']=='+12025550123' and s['phase']=='awaiting_summary_confirmation'
assert '+12025550123' in r['text'] and not r.get('media')
r,s=turn(phone,'Actually, please use +1 202 555 0199 instead.')
assert s['contact_phone']=='+12025550199' and s['phase']=='awaiting_summary_confirmation'
assert '+12025550199' in r['text'] and not r.get('media')
r,s=turn(phone,'yes, those details are correct')
item=store.latest_for_conversation(phone)
assert r.get('media') and item['state']=='demo_payment_pending'
assert item['intake']['contact_phone']=='+12025550199' and item['monetary_snapshot']['total']==300

r,s=turn('synthetic-contact-early-nl','Ik wil voor zondag 6 september 2026 boeken, twee volwassenen en geen kinderen. Mijn naam is Test Gast. Mijn telefoonnummer is +31 6 1234 5678 en we komen zelf naar de pier.')
assert s['contact_phone']=='+31612345678' and s['phase']=='awaiting_summary_confirmation'
assert '+31612345678' in r['text'] and not r.get('media')
r,s=turn('synthetic-contact-local',"I'd like to book Sunday 6 September 2026 for two adults only. My name is Test Guest, we'll meet at the pier and my phone number is 5550123.")
assert not s.get('contact_phone') and s['phase']=='collecting' and not r.get('media')
print(json.dumps(dict(passed=True,model_turns=len(turns),provider_sends=0)),flush=True)
