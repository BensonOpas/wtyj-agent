"""Additive, content-free Anthropic accounting and completed-form observation.

Enabled explicitly per deployment. No prompt/model/retry changes. Local ledger
failures never change the model result or customer workflow; an append-only
fallback is available for replay. Costs are versioned estimates, not invoices.
"""
from __future__ import annotations
import contextvars
import fcntl
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)
PRICE_VERSION = 'anthropic-standard-2026-09-04'
RULE_VERSION = 'consulta-complete-form-v1'
_ACTIVE = contextvars.ContextVar('ai_monitoring_attempt', default=None)
_HOOK_LOCK = threading.Lock()
REQUIRED = ('first_name', 'surnames', 'phone_raw', 'appointment_preference',
            'session_type', 'preferred_clinic', 'callback_preference')


def now():
    return datetime.now(timezone.utc).isoformat()


def enabled():
    return os.environ.get('AI_MONITORING_ENABLED', '').lower() in {'1', 'true'}


def tenant():
    return os.environ.get('TENANT_ID') or os.environ.get('TENANT_SLUG') or 'unknown'


def db_path():
    return Path(os.environ.get('AI_MONITORING_DB', str(Path(__file__).resolve().parents[1] / 'data' / 'ai_monitoring.db')))


def identity(value, channel='whatsapp'):
    # Marina appends a mutable display name to the stable provider ID.
    value = str(value or '').split(' (', 1)[0].strip()
    if not value:
        return None
    return hashlib.sha256(f'{tenant()}:{channel}:{value}'.encode()).hexdigest()


def _connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=.25)
    os.chmod(path, 0o600)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA busy_timeout=250')
    con.executescript('''
      CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, request_id TEXT UNIQUE,
        ts TEXT NOT NULL, payload TEXT NOT NULL);
      CREATE INDEX IF NOT EXISTS requests_ts ON requests(ts);
      CREATE TABLE IF NOT EXISTS leads (key TEXT PRIMARY KEY, payload TEXT NOT NULL);
    ''')
    con.execute('INSERT OR IGNORE INTO metadata VALUES (?,?)', ('instrumented_at', now()))
    con.commit()
    return con


def _fallback(kind, payload):
    try:
        line = json.dumps({'kind': kind, 'payload': payload}, separators=(',', ':')) + '\n'
        with open(str(db_path()) + '.pending.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            fd = os.open(str(db_path()) + '.pending.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, line.encode())
                os.fsync(fd)
            finally:
                os.close(fd)
    except Exception:
        LOG.error('ai_monitoring_persistence_failed kind=%s', kind)


def _write_request(payload):
    try:
        con = _connect()
        try:
            con.execute('''INSERT INTO requests VALUES (?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET request_id=excluded.request_id,
                ts=excluded.ts,payload=excluded.payload
                WHERE json_extract(excluded.payload, '$.status') != 'started'
                   OR json_extract(requests.payload, '$.status') = 'started'
                ''',
                (payload['id'], payload.get('request_id'), payload['started_at'], json.dumps(payload)))
            con.commit()
        finally:
            con.close()
    except sqlite3.IntegrityError:
        # Same provider response must not be charged twice in the ledger.
        LOG.warning('ai_monitoring_duplicate_provider_response')
    except Exception:
        _fallback('request', payload)


def _integer(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def token_usage(usage):
    def get(obj, key):
        return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    result = {k: _integer(get(usage, k)) for k in (
        'input_tokens', 'output_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')}
    creation = get(usage, 'cache_creation')
    result.update({k: _integer(get(creation, k)) for k in ('ephemeral_5m_input_tokens', 'ephemeral_1h_input_tokens')})
    return result


def estimate(model, usage):
    rates = {'claude-sonnet-4-6': (3, 15), 'claude-sonnet-4-5': (3, 15),
             'claude-haiku-4-5-20251001': (1, 5)}
    if model not in rates or any(usage.get(k) is None for k in ('input_tokens', 'output_tokens')):
        return None
    i, o = rates[model]
    write = usage.get('cache_creation_input_tokens') or 0
    one_hour = usage.get('ephemeral_1h_input_tokens') or 0
    five_min = usage.get('ephemeral_5m_input_tokens')
    if five_min is None:
        five_min = max(0, write - one_hour)
    return (usage['input_tokens'] * i + usage['output_tokens'] * o +
            (usage.get('cache_read_input_tokens') or 0) * i * .1 +
            five_min * i * 1.25 + one_hour * i * 2) / 1_000_000


def _request_hook(request):
    state = _ACTIVE.get()
    if state is not None and request.method == 'POST' and request.url.path.endswith('/messages'):
        state['http_attempts'] += 1


def _response_hook(response):
    state = _ACTIVE.get()
    if state is not None and response.request.url.path.endswith('/messages'):
        state['http_statuses'].append(response.status_code)
        req_id = response.headers.get('request-id')
        if req_id:
            state['last_http_request_id'] = req_id


def _install_hooks(client):
    http = getattr(client, '_client', None)
    hooks = getattr(http, 'event_hooks', None)
    if not isinstance(hooks, dict):
        return False
    with _HOOK_LOCK:
        for kind, hook in [('request', _request_hook), ('response', _response_hook)]:
            if hook not in hooks.setdefault(kind, []):
                hooks[kind].append(hook)
    return True


def create_message(client, *, monitor_feature, monitor_conversation=None,
                   monitor_channel='internal', monitor_operation_id=None,
                   monitor_attempt=1, **kwargs):
    if not enabled():
        return client.messages.create(**kwargs)
    record = {'id': uuid.uuid4().hex, 'started_at': now(), 'tenant': tenant(),
              'environment': os.environ.get('AI_MONITORING_ENVIRONMENT', 'unclassified'),
              'feature': monitor_feature, 'channel': monitor_channel,
              'conversation_key': identity(monitor_conversation, monitor_channel),
              'operation_id': monitor_operation_id, 'application_attempt': monitor_attempt,
              'requested_model': kwargs.get('model'), 'status': 'started',
              'source': 'instrumented', 'price_version': PRICE_VERSION,
              'build': os.environ.get('AI_MONITORING_BUILD', 'unknown')}
    try:
        _write_request(record)
    except Exception:
        LOG.error('ai_monitoring_start_failed')
    state = {'http_attempts': 0, 'http_statuses': []}
    try:
        hooks_ok = _install_hooks(client)
    except Exception:
        hooks_ok = False
    token = _ACTIVE.set(state)
    began = time.monotonic()
    try:
        response = client.messages.create(**kwargs)
    except BaseException as exc:
        record.update(status='error', error_type=type(exc).__name__, ended_at=now(),
                      http_status=getattr(exc, 'status_code', None),
                      request_id=getattr(exc, 'request_id', None) or state.get('last_http_request_id'),
                      estimated_usd=None)
        raise
    else:
        record.update(status='success', ended_at=now(), estimated_usd=None)
        try:
            usage = token_usage(getattr(response, 'usage', None))
            model = getattr(response, 'model', None)
            model = model if isinstance(model, str) else kwargs.get('model')
            req_id = getattr(response, '_request_id', None)
            req_id = req_id if isinstance(req_id, str) else state.get('last_http_request_id')
            record.update(model=model, request_id=req_id, usage=usage,
                          estimated_usd=estimate(model, usage),
                          model_source='response' if isinstance(getattr(response, 'model', None), str) else 'request_fallback')
        except Exception:
            record['metadata_error'] = True
            LOG.error('ai_monitoring_response_metadata_failed')
        return response
    finally:
        _ACTIVE.reset(token)
        record.update(duration_ms=round((time.monotonic()-began)*1000),
                      http_attempts=state['http_attempts'] if hooks_ok else None,
                      http_statuses=state['http_statuses'], attempt_visibility='http_hooks' if hooks_ok else 'unknown')
        # Persist success before caller parsing; failure never changes delivery.
        try:
            _write_request(record)
        except Exception:
            LOG.error('ai_monitoring_record_failed')


def complete_fields(form):
    flags = {k: bool(str(form.get(k) or '').strip()) for k in REQUIRED}
    raw = str(form.get('phone_raw') or '').strip()
    flags['phone_raw'] = bool(re.fullmatch(r'[+0-9().\s-]+', raw) and 9 <= len(re.sub(r'\D', '', raw)) <= 15)
    return flags


def _store_lead(payload):
    con = _connect()
    try:
        con.execute('BEGIN IMMEDIATE')
        old = con.execute('SELECT payload FROM leads WHERE key=?', (payload['key'],)).fetchone()
        old = json.loads(old[0]) if old else None
        if old and payload['observed_at'] < old['observed_at']:
            return
        if old:
            payload['first_observed_at'] = old['first_observed_at']
            payload['completed_at'] = old.get('completed_at')
            payload['completion_source'] = old.get('completion_source')
            if not old.get('ever_complete') and payload['currently_complete']:
                payload['completed_at'] = payload['observed_at']
                payload['completion_source'] = 'observed_transition'
            payload['ever_complete'] = bool(old.get('ever_complete') or payload['currently_complete'])
        con.execute('INSERT OR REPLACE INTO leads VALUES (?,?)', (payload['key'], json.dumps(payload)))
        con.commit()
    finally:
        con.close()


def observe_form(form, *, baseline=False, observed_at=None):
    if not enabled() or tenant() != 'consulta-despertares' or not form:
        return
    at = observed_at or now()
    flags = complete_fields(form)
    complete = all(flags.values())
    payload = {'key': identity(form.get('conversation_id'), form.get('channel') or 'whatsapp'),
               'lead_id': form['id'], 'tenant': tenant(), 'rule_version': RULE_VERSION,
               'first_customer_at': form.get('first_customer_at') or form.get('created_at'),
               'first_observed_at': at, 'observed_at': at,
               'field_presence': flags, 'currently_complete': complete, 'ever_complete': complete,
               'completed_at': at if complete and not baseline else None,
               'completion_source': ('preexisting_snapshot' if baseline else 'observed_transition') if complete else None}
    try:
        _store_lead(payload)
    except Exception:
        _fallback('lead', payload)


def observe_conversation(conversation_id, *, baseline=False):
    if not enabled() or tenant() != 'consulta-despertares':
        return
    try:
        from shared import state_registry as registry
        # Read-only connection avoids the registry's lazy schema migrations.
        con = sqlite3.connect('file:' + os.path.abspath(registry.DB_PATH) + '?mode=ro', uri=True, timeout=.25)
        con.row_factory = sqlite3.Row
        try:
            row = con.execute('SELECT * FROM follow_up_requests WHERE conversation_id=?', (conversation_id,)).fetchone()
            if not row:
                return
            form = dict(row)
            state = con.execute('SELECT fields_json FROM whatsapp_booking_state WHERE phone=?', (conversation_id,)).fetchone()
            fields = json.loads(state[0] or '{}') if state else {}
            form.update(registry._follow_up_context(fields))
            first = con.execute("SELECT MIN(created_at) FROM whatsapp_threads WHERE phone=? AND role='user'", (conversation_id,)).fetchone()
            form['first_customer_at'] = first[0] if first else None
        finally:
            con.close()
        observe_form(form, baseline=baseline)
    except Exception:
        LOG.error('ai_monitoring_lead_observation_failed')


def seed_forms():
    from shared import state_registry as registry
    con = sqlite3.connect('file:' + os.path.abspath(registry.DB_PATH) + '?mode=ro', uri=True)
    try:
        ids = [r[0] for r in con.execute('SELECT conversation_id FROM follow_up_requests')]
    finally:
        con.close()
    for cid in ids:
        observe_conversation(cid, baseline=True)
    return len(ids)


def import_legacy(log_path, start='2026-09-01T00:00:00+00:00'):
    con = _connect()
    try:
        cutoff = con.execute("SELECT value FROM metadata WHERE key='instrumented_at'").fetchone()[0]
    finally:
        con.close()
    count = 0
    for line in Path(log_path).open():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if not start <= str(r.get('ts', '')) < cutoff or 'input_tokens' not in r:
            continue
        channel = r.get('channel') or 'unknown'
        record = {'id': 'legacy-' + hashlib.sha256(line.encode()).hexdigest(),
                  'started_at': r['ts'], 'ended_at': r['ts'], 'status': 'success',
                  'tenant': tenant(), 'environment': os.environ.get('AI_MONITORING_ENVIRONMENT', 'unclassified'),
                  'source': 'legacy_reconstruction', 'feature': r.get('event'), 'channel': channel,
                  'conversation_key': identity(r.get('from_id') or r.get('customer_id'), channel),
                  'model': r.get('model') or 'claude-sonnet-4-6',
                  'model_source': 'legacy_logged' if r.get('model') else 'inferred_sonnet',
                  'request_id': None, 'usage': token_usage(r), 'price_version': PRICE_VERSION,
                  'http_attempts': None, 'attempt_visibility': 'unknown'}
        record['estimated_usd'] = estimate(record['model'], record['usage'])
        _write_request(record)
        count += 1
    return count


def report(month):
    if not re.fullmatch(r'\d{4}-\d{2}', month):
        raise ValueError('Use YYYY-MM')
    year, mon = map(int, month.split('-'))
    start = datetime(year, mon, 1, tzinfo=timezone.utc).isoformat()
    end = datetime(year + (mon == 12), 1 if mon == 12 else mon+1, 1, tzinfo=timezone.utc).isoformat()
    con = _connect()
    try:
        records = [json.loads(r[0]) for r in con.execute('SELECT payload FROM requests WHERE ts>=? AND ts<?', (start, end))]
        all_records = [json.loads(r[0]) for r in con.execute('SELECT payload FROM requests')]
        leads = [json.loads(r[0]) for r in con.execute('SELECT payload FROM leads')]
        metadata = dict(con.execute('SELECT key,value FROM metadata'))
    finally:
        con.close()
    def group(items):
        costs = [r.get('estimated_usd') for r in items if r['status']=='success']
        return {'requests': len(items), 'successes': sum(r['status']=='success' for r in items),
                'errors': sum(r['status']=='error' for r in items),
                'pending': sum(r['status']=='started' for r in items),
                'unpriced_successes': sum(v is None for v in costs),
                'estimated_usd': round(sum(v for v in costs if v is not None), 8)}
    completed = [l for l in leads if l.get('completed_at') and start<=l['completed_at']<end]
    preexisting_new = [l for l in leads if l.get('completion_source')=='preexisting_snapshot'
                       and start<=str(l.get('first_customer_at') or '')<end]
    cost_to_complete=[]
    for lead in completed:
        rr=[r for r in all_records if r.get('conversation_key')==lead['key'] and r['started_at']<=lead['completed_at']]
        cost_to_complete.append(group(rr)['estimated_usd'])
    import statistics
    cohort=[l for l in leads if start<=str(l.get('first_customer_at') or '')<end]
    total=group(records)
    denominator=len(completed)+len(preexisting_new)
    pending_file=Path(str(db_path())+'.pending.jsonl')
    return {'generated_at':now(), 'month_utc':month, 'tenant':tenant(),
            'environment':os.environ.get('AI_MONITORING_ENVIRONMENT','unclassified'),
            'instrumented_at':metadata.get('instrumented_at'), 'rule_version':RULE_VERSION,
            'price_version':PRICE_VERSION, 'total':total,
            'by_source':{src:group([r for r in records if r['source']==src]) for src in sorted({r['source'] for r in records})},
            'by_feature':{f:group([r for r in records if r['feature']==f]) for f in sorted({r['feature'] for r in records})},
            'daily':{day:group([r for r in records if r['started_at'][:10]==day]) for day in sorted({r['started_at'][:10] for r in records})},
            'overhead_without_conversation':group([r for r in records if not r.get('conversation_key')]),
            'http_retries_observed':sum(max(0,(r.get('http_attempts') or 0)-1) for r in records),
            'attempt_visibility_unknown':sum(r.get('http_attempts') is None for r in records),
            'observed_form_completions':len(completed),
            'already_complete_at_start_with_first_contact_this_month':len(preexisting_new),
            'month_completed_forms_known':denominator,
            'customer_costs':customer_costs(records, all_records, leads),
            'cohort':{'first_contact_this_month':len(cohort),'ever_complete':sum(l['ever_complete'] for l in cohort),
                      'currently_incomplete':sum(not l['currently_complete'] for l in cohort)},
            'mean_recorded_cost_to_observed_completion_usd':statistics.mean(cost_to_complete) if cost_to_complete else None,
            'median_recorded_cost_to_observed_completion_usd':statistics.median(cost_to_complete) if cost_to_complete else None,
            'month_ai_spend_per_known_completed_form_usd':total['estimated_usd']/denominator if denominator else None,
            'post_completion_cost':group([r for r in records if any(l.get('completed_at') and r.get('conversation_key')==l['key'] and r['started_at']>l['completed_at'] for l in leads)]),
            'fallback_file_bytes':sum(p.stat().st_size for p in db_path().parent.glob(db_path().name+'.pending*jsonl')),
            'limitations':['Estimates, not provider invoices. Shared API key unchanged.',
                          'Legacy records omit some operations and cache/request metadata.',
                          'Preexisting complete forms have unknown exact completion time.',
                          'One existing follow-up form per provider conversation; edits do not create new leads.',
                          'Internal tests using real production contact IDs require explicit exclusion; none inferred.']}


def customer_costs(month_records, all_records, leads):
    """Full customer spend never stops at form completion. Merge only known IDs."""
    aliases = {}
    try:
        from shared import state_registry as registry
        con = sqlite3.connect('file:' + os.path.abspath(registry.DB_PATH) + '?mode=ro', uri=True, timeout=.25)
        try:
            for customer_id, kind, value in con.execute('SELECT customer_id,type,value FROM customer_identifiers'):
                channel = {'wa_conversation_id':'whatsapp', 'phone':'whatsapp', 'email':'email'}.get(kind)
                if channel:
                    aliases[identity(value, channel)] = hashlib.sha256(f'{tenant()}:customer:{customer_id}'.encode()).hexdigest()
        finally:
            con.close()
    except Exception:
        # Unresolved identities remain separate; never merge on display name.
        pass
    def key(r):
        cid = r.get('conversation_key')
        return aliases.get(cid, cid)
    keys = {key(r) for r in month_records if key(r) and r['status']=='success'}
    entries=[]
    complete_keys={aliases.get(l['key'], l['key']) for l in leads if l['ever_complete']}
    for cid in keys:
        current=[r for r in month_records if key(r)==cid]
        lifetime=[r for r in all_records if key(r)==cid]
        successful=[r for r in current if r['status']=='success']
        entries.append({'customer_key':cid, 'identity_basis':'customer_registry' if cid in aliases.values() else 'conversation_fallback',
                        'month_estimated_usd':round(sum(r.get('estimated_usd') or 0 for r in successful),8),
                        'all_recorded_estimated_usd':round(sum(r.get('estimated_usd') or 0 for r in lifetime if r['status']=='success'),8),
                        'month_successful_requests':len(successful),
                        'month_unpriced_successes':sum(r.get('estimated_usd') is None for r in successful),
                        'month_errors':sum(r['status']=='error' for r in current),
                        'form_ever_complete':cid in complete_keys,
                        'first_recorded_request':min(r['started_at'] for r in lifetime),
                        'last_recorded_request':max(r['started_at'] for r in lifetime)})
    entries.sort(key=lambda e:e['month_estimated_usd'], reverse=True)
    costs=[e['month_estimated_usd'] for e in entries]
    import statistics, math
    overhead=sum(r.get('estimated_usd') or 0 for r in month_records if not key(r) and r['status']=='success')
    return {'definition':'All recorded customer-linked AI work, including every request before and after form completion.',
            'customers_with_successful_ai_requests':len(entries),
            'total_customer_linked_month_usd':round(sum(costs),8),
            'mean_month_cost_per_customer_usd':statistics.mean(costs) if costs else None,
            'mean_all_recorded_cost_per_active_customer_usd':statistics.mean([e['all_recorded_estimated_usd'] for e in entries]) if entries else None,
            'median_month_cost_per_customer_usd':statistics.median(costs) if costs else None,
            'p90_month_cost_per_customer_usd':sorted(costs)[max(0, math.ceil(len(costs)*.9)-1)] if costs else None,
            'shared_overhead_month_usd':round(overhead,8),
            'blended_month_ai_spend_per_served_customer_usd':(sum(costs)+overhead)/len(entries) if entries else None,
            'customers':entries,
            'coverage_note':'All-recorded totals start at available imported/monitored history, not guaranteed customer lifetime. Costs without a customer stay in shared overhead.'}


def replay_pending():
    """Replay fallback records idempotently; a crash leaves a recoverable spool."""
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path)+'.pending.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pending = Path(str(path)+'.pending.jsonl')
        if pending.exists() and pending.stat().st_size:
            pending.rename(str(path)+'.pending-'+uuid.uuid4().hex+'.jsonl')
    count = 0
    for spool in path.parent.glob(path.name+'.pending-*.jsonl'):
        # Only one replay worker may consume a spool at a time.
        with spool.open() as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            for line in handle:
                try:
                    entry = json.loads(line)
                    if entry['kind']=='request':
                        _write_request(entry['payload'])
                    elif entry['kind']=='lead':
                        try:
                            _store_lead(entry['payload'])
                        except Exception:
                            _fallback('lead', entry['payload'])
                    else:
                        raise ValueError('Unknown record kind')
                    count += 1
                except (ValueError, KeyError):
                    LOG.error('ai_monitoring_invalid_fallback_record')
                    # Keep evidence; do not silently discard malformed records.
                    break
            else:
                spool.unlink(missing_ok=True)
    return count
