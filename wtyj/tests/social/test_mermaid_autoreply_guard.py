from datetime import datetime, timedelta, timezone
from agents.social.mermaid_autoreply_guard import repeated_automatic_reply
from shared import state_registry
from test_mermaid_soft_review import review_runtime, CONVERSATION, _flush, _rows, _understood

AUTO='Thank you for contacting Example Business. How can we help you today? Please tell us what you need.'

def history(text=AUTO):
    now=datetime.now(timezone.utc).isoformat()
    return [{'role':role,'text':value,'created_at':now} for role,value in [('user',text),('assistant','How can I help with a Mermaid trip?'),('user',text),('assistant','What would you like to know?')]]

def test_only_proven_repeated_automatic_reply_is_suppressed():
    assert repeated_automatic_reply(AUTO,history())
    assert not repeated_automatic_reply(AUTO,history()[:2])
    assert not repeated_automatic_reply('Hello, are you there?',history('Hello, are you there?'))
    genuine='I need some assistance for my husband on the boat. Can you please help me arrange this?'
    assert not repeated_automatic_reply(genuine,history(genuine))
    assert not repeated_automatic_reply(AUTO,history(),now=datetime.now(timezone.utc)+timedelta(minutes=11))
    assert not repeated_automatic_reply(AUTO,history()+[{'role':'operator','text':'A person is here','created_at':datetime.now(timezone.utc).isoformat()}])

def test_pipeline_breaks_loop_and_next_real_message_still_gets_answer(review_runtime):
    model,send,_=review_runtime
    for item in history():
        state_registry.dm_store_message(conversation_id=CONVERSATION,channel='whatsapp',role=item['role'],text=item['text'])
    _flush('auto-loop',AUTO)
    assert not model.called and not send.called
    assert _rows("SELECT status,reason FROM inbound_processing_events WHERE message_id='auto-loop'")==[('ignored','mermaid_repeated_automatic_reply')]
    assert not state_registry.get_ai_muted(CONVERSATION)
    model.return_value=_understood('question','Breakfast is included.')
    _flush('real-question','Is breakfast included?')
    assert model.call_count==send.call_count==1
    assert send.call_args.args[3]=='Breakfast is included.'
