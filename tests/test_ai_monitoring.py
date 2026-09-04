import ast
import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import anthropic
import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'wtyj'))
from shared import ai_monitoring as m

@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setenv('AI_MONITORING_ENABLED', '1')
    monkeypatch.setenv('TENANT_ID', 'consulta-despertares')
    monkeypatch.setenv('AI_MONITORING_ENVIRONMENT', 'test')
    monkeypatch.setenv('AI_MONITORING_DB', str(tmp_path/'monitor.db'))

def rows():
    con=m._connect()
    try: return [json.loads(r[0]) for r in con.execute('SELECT payload FROM requests')]
    finally: con.close()

def client():
    response=SimpleNamespace(model='claude-sonnet-4-6', _request_id='req-example',
        usage=SimpleNamespace(input_tokens=1000, output_tokens=100), content='private reply')
    return SimpleNamespace(messages=SimpleNamespace(create=Mock(return_value=response)))

def call(c, **extra):
    return m.create_message(c, monitor_feature='reply', monitor_conversation='private-phone (private-name)',
        monitor_channel='whatsapp', model='claude-sonnet-4-6', messages=[{'role':'user','content':'private medical content'}], max_tokens=500, **extra)

def test_disabled_exact_forwarding(monkeypatch):
    monkeypatch.delenv('AI_MONITORING_ENABLED')
    c=client(); result=call(c)
    assert result is c.messages.create.return_value
    assert c.messages.create.call_args.kwargs=={'model':'claude-sonnet-4-6','messages':[{'role':'user','content':'private medical content'}],'max_tokens':500}
    assert not m.db_path().exists()

def test_success_before_parsing_and_private():
    c=client(); result=call(c)
    with pytest.raises(ValueError): json.loads(result.content)
    r=rows()[0]
    assert r['status']=='success' and r['estimated_usd']==pytest.approx(.0045)
    assert r['model_source']=='response'
    encoded=json.dumps(r)
    for secret in ['private-phone','private-name','private medical content','private reply']:
        assert secret not in encoded
    assert m.identity('private-phone (another name)')==r['conversation_key']

def test_errors_preserved_no_error_text():
    c=client(); error=RuntimeError('private error text'); c.messages.create.side_effect=error
    with pytest.raises(RuntimeError) as found: call(c)
    assert found.value is error
    r=rows()[0]; assert r['status']=='error' and r['estimated_usd'] is None
    assert 'private error text' not in json.dumps(r)

def test_sdk_retry_metadata_and_cache():
    attempts=[]
    def transport(request):
        attempts.append(request)
        if len(attempts)==1:
            return httpx.Response(500, headers={'request-id':'req-failed','retry-after-ms':'1'}, json={'type':'error','error':{'type':'api_error','message':'test'}})
        return httpx.Response(200, headers={'request-id':'req-success'}, json={
            'id':'msg_mock','type':'message','role':'assistant','model':'claude-sonnet-4-6',
            'content':[{'type':'text','text':'mock'}],'stop_reason':'end_turn','stop_sequence':None,
            'usage':{'input_tokens':100,'output_tokens':10,'cache_creation_input_tokens':200,
                     'cache_read_input_tokens':500,'cache_creation':{'ephemeral_5m_input_tokens':100,'ephemeral_1h_input_tokens':100}}})
    with anthropic.Anthropic(api_key='test-not-a-real-key', max_retries=1, http_client=httpx.Client(transport=httpx.MockTransport(transport))) as c:
        result=call(c)
    r=rows()[0]
    assert result._request_id=='req-success'
    assert r['http_attempts']==2 and r['http_statuses']==[500,200]
    assert r['estimated_usd']==pytest.approx(.001575)
    assert len(attempts)==2

def test_concurrent_sdk_attribution():
    def transport(request):
        idx=json.loads(request.content)['max_tokens']
        return httpx.Response(200, headers={'request-id':f'req-{idx}'}, json={
            'id':f'msg_{idx}','type':'message','role':'assistant','model':'claude-sonnet-4-6',
            'content':[{'type':'text','text':'mock'}],'stop_reason':'end_turn','stop_sequence':None,
            'usage':{'input_tokens':idx,'output_tokens':1}})
    with anthropic.Anthropic(api_key='test', http_client=httpx.Client(transport=httpx.MockTransport(transport))) as c:
        def run(idx):
            return m.create_message(c,monitor_feature='reply',monitor_conversation=str(idx),monitor_channel='whatsapp',model='claude-sonnet-4-6',max_tokens=idx,messages=[])
        with ThreadPoolExecutor(max_workers=8) as pool: list(pool.map(run,range(1,25)))
    m.replay_pending()
    rr=rows(); assert len(rr)==24
    for r in rr:
        idx=r['usage']['input_tokens']
        assert r['conversation_key']==m.identity(str(idx)) and r['request_id']==f'req-{idx}' and r['http_attempts']==1

def form(**extra):
    value={'id':1,'conversation_id':'test-person','channel':'whatsapp','created_at':'2026-09-02T00:00:00+00:00',
           **{k:'filled' for k in m.REQUIRED},'phone_raw':'+34 600 000 000'}
    value.update(extra); return value

def test_form_requirements_and_once():
    assert all(m.complete_fields(form()).values()) # optional consultation reason absent
    for field in m.REQUIRED:
        assert not all(m.complete_fields(form(**{field:''})).values())
    assert not all(m.complete_fields(form(phone_raw='provider-123456789')).values())
    m.observe_form(form(surnames=''),baseline=True,observed_at='2026-09-04T00:00:00+00:00')
    m.observe_form(form(),observed_at='2026-09-05T00:00:00+00:00')
    m.observe_form(form(surnames=''),observed_at='2026-09-06T00:00:00+00:00')
    m.observe_form(form(),observed_at='2026-09-07T00:00:00+00:00')
    r=m.report('2026-09'); assert r['observed_form_completions']==1
    con=m._connect(); l=json.loads(con.execute('SELECT payload FROM leads').fetchone()[0]);con.close()
    assert l['completed_at']=='2026-09-05T00:00:00+00:00'
    assert 'filled' not in json.dumps(l) and '+34' not in json.dumps(l)

def test_baseline_not_new_conversion():
    m.observe_form(form(created_at='2026-08-02T00:00:00+00:00'),baseline=True)
    r=m.report('2026-09')
    assert r['observed_form_completions']==0 and r['month_completed_forms_known']==0


def test_customer_full_cost_includes_after_lead_and_earlier_month():
    records=[{'id':str(i),'conversation_key':'customer-1','status':'success','estimated_usd':cost,'started_at':ts}
        for i,(cost,ts) in enumerate([(1,'2026-08-31'),(2,'2026-09-01'),(3,'2026-09-03')])]
    records.append({'id':'other','conversation_key':'customer-2','status':'success','estimated_usd':4,'started_at':'2026-09-02'})
    records.append({'id':'overhead','conversation_key':None,'status':'success','estimated_usd':2,'started_at':'2026-09-02'})
    r=m.customer_costs(records[1:],records,[{'key':'customer-1','ever_complete':True,'completed_at':'2026-09-02'}])
    e=next(c for c in r['customers'] if c['customer_key']=='customer-1')
    assert e['all_recorded_estimated_usd']==6 and e['month_estimated_usd']==5
    assert r['mean_month_cost_per_customer_usd']==4.5
    assert r['shared_overhead_month_usd']==2 and r['blended_month_ai_spend_per_served_customer_usd']==5.5

def test_unknown_model_and_missing_usage():
    assert m.estimate('new-model',{'input_tokens':1,'output_tokens':1}) is None
    assert m.estimate('claude-sonnet-4-6',m.token_usage(None)) is None

def test_persistence_failure_fallback_and_no_started_regression(monkeypatch):
    original=m._connect
    monkeypatch.setattr(m,'_connect',Mock(side_effect=sqlite3.OperationalError('test busy')))
    c=client(); assert call(c) is c.messages.create.return_value
    pending=Path(str(m.db_path())+'.pending.jsonl'); assert pending.stat().st_size>0
    monkeypatch.setattr(m,'_connect',original)
    assert m.replay_pending()==2
    r=rows()[0]; assert r['status']=='success'
    older={**r,'status':'started'};m._write_request(older)
    assert rows()[0]['status']=='success'

def test_metadata_failure_never_breaks_response(monkeypatch):
    monkeypatch.setattr(m,'token_usage',Mock(side_effect=ValueError('bad metadata')))
    c=client();assert call(c) is c.messages.create.return_value
    assert rows()[0]['metadata_error'] is True

def test_legacy_idempotent_cutoff_month_boundary(tmp_path):
    c=m._connect();c.execute("UPDATE metadata SET value='2026-09-04T00:00:00+00:00' WHERE key='instrumented_at'");c.commit();c.close()
    logfile=tmp_path/'agent.log'
    values=[{'ts':ts,'event':'response_generated','channel':'whatsapp','from_id':'private-phone (name)','input_tokens':100,'output_tokens':10}
            for ts in ['2026-08-31T23:59:59+00:00','2026-09-01T00:00:00+00:00','2026-09-04T00:00:00+00:00']]
    logfile.write_text('\n'.join(json.dumps(v) for v in values)+'\n')
    assert m.import_legacy(logfile,start='2026-08-01')==2
    m.import_legacy(logfile,start='2026-08-01')
    assert len(rows())==2 and m.report('2026-09')['total']['requests']==1
    with pytest.raises(ValueError):m.report('2026-13')

def test_all_twelve_model_call_arguments_unchanged():
    root=Path(__file__).resolve().parents[1]
    paths=['agents/marina/marina_agent.py','agents/social/dm_agent.py','agents/social/content_agent.py','dashboard/api.py','dashboard/escalation_summary.py']
    count=0
    for path in paths:
        repo_path='wtyj/'+path
        old=ast.parse(subprocess.check_output(['git','show','c42adcb:'+repo_path],cwd=root,text=True))
        new=ast.parse((root/repo_path).read_text())
        before=[n for n in ast.walk(old) if isinstance(n,ast.Call) and ast.unparse(n.func)=='client.messages.create']
        after=[n for n in ast.walk(new) if isinstance(n,ast.Call) and ast.unparse(n.func)=='ai_monitoring.create_message']
        assert len(before)==len(after)
        for a,b in zip(before,after):
            assert [ast.dump(k) for k in a.keywords]==[ast.dump(k) for k in b.keywords if not (k.arg or '').startswith('monitor_')]
        count+=len(after)
    assert count==12

def test_registry_aliases_and_form_read_only(monkeypatch, tmp_path):
    from shared import state_registry as registry
    db=tmp_path/'customer.db';monkeypatch.setattr(registry,'DB_PATH',str(db))
    con=sqlite3.connect(db)
    con.executescript('''CREATE TABLE customer_identifiers(customer_id INTEGER,type TEXT,value TEXT);
        CREATE TABLE follow_up_requests(id INTEGER,conversation_id TEXT,channel TEXT,created_at TEXT,
        first_name TEXT,surnames TEXT,phone_raw TEXT,callback_preference TEXT,status TEXT);
        CREATE TABLE whatsapp_booking_state(phone TEXT,fields_json TEXT);
        CREATE TABLE whatsapp_threads(phone TEXT,role TEXT,created_at TEXT);''')
    con.executemany('INSERT INTO customer_identifiers VALUES (?,?,?)',[(1,'wa_conversation_id','provider1'),(1,'phone','34600000000')])
    con.execute('INSERT INTO follow_up_requests VALUES (1,?,?,?,?,?,?,?,?)',('provider1','whatsapp','2026-09-02T00:00:00+00:00','Name','Surname','+34 600 000 000','WhatsApp','copied'))
    con.execute('INSERT INTO whatsapp_booking_state VALUES (?,?)',('provider1',json.dumps({'session_type':'online','preferred_clinic':'Madrid','appointment_preference':'tomorrow'})))
    con.execute('INSERT INTO whatsapp_threads VALUES (?,?,?)',('provider1','user','2026-09-01T00:00:00+00:00'))
    con.commit();before=list(con.iterdump());con.close()
    m.observe_conversation('provider1',baseline=True)
    r=m.report('2026-09');assert r['month_completed_forms_known']==1
    con=sqlite3.connect(db);assert before==list(con.iterdump());con.close()
    rr=[{'conversation_key':m.identity(cid),'status':'success','estimated_usd':cost,'started_at':'2026-09-02'} for cid,cost in [('provider1',1),('34600000000',2)]]
    r=m.customer_costs(rr,rr,[])
    assert len(r['customers'])==1 and r['customers'][0]['month_estimated_usd']==3
