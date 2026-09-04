"""Explicit child ages remain facts and formal copy avoids conversational labels."""
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from pypdf import PdfReader
from agents.marina import marina_agent
from agents.social import mermaid_documents as docs
from agents.social import mermaid_guest_experience as guest
from agents.social import mermaid_model_recovery as recovery
from agents.social import mermaid_reservation_store as store
from agents.social import mermaid_reservation_workflow as workflow
from shared import config_loader, state_registry, mermaid_catalog
from shared.mermaid_guest_ages import normalize_child_ages

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
 monkeypatch.setattr(config_loader,'_CONFIG_PATH',str(Path(__file__).resolve().parents[3]/'clients/mermaid/config/client.json'));monkeypatch.setattr(config_loader,'_cache',{})
 monkeypatch.setattr(state_registry,'DB_PATH',str(tmp_path/'state.db'));monkeypatch.setattr(state_registry,'_alert_dispatcher',None)

def understood(**kw):
 base=dict(language='en',mermaid_action='question',fields={},reply='You can explore the island.',confidence='high',requires_human=False,has_open_question=True,security_event='none',calendar_request='none',status_request='none')
 base.update(kw);return base

def test_nine_month_age_is_saved_during_information_question_and_later_summary(monkeypatch):
 model=Mock(side_effect=[understood(fields={'infants':1,'child_ages':[{'value':9,'unit':'months'}]}),understood(mermaid_action='details',has_open_question=False,reply='Got it.',fields={'trip_date':'2026-09-13','adults':3,'children':0,'customer_name':'Calvin test','contact_phone':'+59996881585','pickup_preference':'pier'})])
 monkeypatch.setattr(marina_agent,'process_message',model)
 workflow.process_model_turn({'from':'guest','text':'What can I do? We have a 9 month old baby','message_id':'one'},None)
 result=workflow.process_model_turn({'from':'guest','text':'The rest of our details','message_id':'two'},None)
 saved=state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']
 assert saved['child_ages']==[{'value':9,'unit':'months'}]
 assert '3 adults · 1 infant (9 months)' in result.text
 assert 'little one' not in result.text and '\n\n*Transport*\n' in result.text
 assert model.call_count==2

@pytest.mark.parametrize('locale,expected',[('en','infant (9 months)'),('nl','baby (9 maanden)'),('de','Säugling (9 Monate)'),('es','bebé (9 meses)'),('pap','bebé (9 luna)'),('pt','bebê (9 meses)')])
def test_formal_copy_uses_known_age_in_every_language(locale,expected):
 text=guest.party_text({'adults':3,'children':0,'infants':1,'child_ages':[{'value':9,'unit':'months'}]},locale)
 assert expected in text and '0–3' not in text

def test_unknown_age_uses_band_without_inventing_a_number():
 assert guest.party_text({'adults':1,'children':0,'infants':1},'en')=='1 adult · 1 child (0–3)'

def test_validation_and_summary_identity_preserve_legacy():
 base={'trip_date':'2026-09-13','adults':3,'children':0,'infants':1,'customer_name':'C','pickup_preference':'pier','language':'en'}
 assert normalize_child_ages([{'value':9,'unit':'months'}],base)==[{'value':9,'unit':'months'}]
 assert normalize_child_ages([{'value':5,'unit':'years'}],base) is None
 assert normalize_child_ages([{'value':9,'unit':'weeks'}],base) is None
 assert store._summary_version(base)==store._summary_version(dict(base))
 assert store._summary_version(base)!=store._summary_version({**base,'child_ages':[{'value':9,'unit':'months'}]})
 assert store._money_snapshot(base,mermaid_catalog.get_catalog())==store._money_snapshot({**base,'child_ages':[{'value':9,'unit':'months'}]},mermaid_catalog.get_catalog())

def test_array_contract_is_accepted_and_malformed_age_cannot_confirm(monkeypatch):
 schema=__import__('agents.social.mermaid_understanding',fromlist=['MERMAID_TOOL']).MERMAID_TOOL['input_schema']['properties']['fields']['properties']['child_ages']
 assert recovery._valid_schema_value([{'value':9,'unit':'months'}],schema)
 assert not recovery._valid_schema_value([{'value':9,'unit':'weeks'}],schema)
 fields={'language':'en','phase':'awaiting_summary_confirmation','trip_date':'2026-09-13','adults':3,'children':0,'infants':1,'customer_name':'C','contact_phone':'+59996881585','pickup_preference':'pier'}
 state_registry.wa_save_booking_state('guest',{'mermaid_intake':fields},{})
 monkeypatch.setattr(marina_agent,'process_message',Mock(return_value=understood(mermaid_action='confirm_summary',has_open_question=False,reply='Okay',fields={'child_ages':[{'value':5,'unit':'years'}]})))
 result=workflow.process_model_turn({'from':'guest','text':'yes','message_id':'bad'},None)
 assert result.action is None and result.phase=='awaiting_summary_confirmation'


def test_reducing_band_discards_uncertain_age(monkeypatch):
 fields={'language':'en','phase':'collecting','children':0,'infants':2,'child_ages':[{'value':9,'unit':'months'},{'value':2,'unit':'years'}]}
 state_registry.wa_save_booking_state('guest',{'mermaid_intake':fields},{})
 monkeypatch.setattr(marina_agent,'process_message',Mock(return_value=understood(fields={'infants':1})))
 workflow.process_model_turn({'from':'guest','text':'Actually one child','message_id':'shrink'},None)
 assert 'child_ages' not in state_registry.wa_get_booking_state('guest')['fields']['mermaid_intake']


def test_known_age_appears_in_one_page_quote(tmp_path):
 fields={'trip_date':'2026-09-13','adults':3,'children':0,'infants':1,
         'child_ages':[{'value':9,'unit':'months'}],'customer_name':'Calvin test',
         'contact_phone':'+59996881585','pickup_preference':'pier','language':'en',
         'phase':'summary_confirmed'}
 item=store.confirm_reservation('pdf-age',fields,idempotency_key='confirm')
 target=tmp_path/'age.pdf'
 docs.render_quote_pdf(item,target)
 reader=PdfReader(target)
 text=' '.join((page.extract_text() or '') for page in reader.pages)
 assert len(reader.pages)==1
 assert 'infant (9 months)' in text
 assert 'little one' not in text
