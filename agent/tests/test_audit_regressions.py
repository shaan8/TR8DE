"""Regressions from the 20 October 2026 external audit of ccc2aaf, formerly b4244b8 (SECURITY.md). Each failed on that commit.
Local Anvil chain, scripted models, test keys only: no production RPC, model keys, messaging.
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tests.conftest import chain_env  # noqa: F401
from tests.test_integration import env, coord, day, honest_checker, n_deals  # noqa: F401
from tests.test_negotiation_chain import svc, agree  # noqa: F401
from tiwala_agent.audit import AuditLog
from tiwala_agent.llm import ScriptedLLM, LLMResponse, ToolCall
from tiwala_agent.models import PHP, Status
from tiwala_agent.negotiation import State


def clean_plans(env):
    (env['data'] / 'plans.json').write_text(json.dumps({'buffer': 0, 'inflows': [], 'planned': []}))


def draft(env):
    return {'supplier': 'Lumen Textiles', 'total_php': 10000, 'down_pct': 10,
            'deadline': day(env['chain'], 10), 'po_ref': 'PO-880'}


REQUEST = 'Create escrow for Lumen PO-880, PHP 10,000, 10% down, delivery in 10 days'


def test_one_request_cannot_create_the_same_po_twice(env):
    clean_plans(env)
    c = ScriptedLLM([LLMResponse('', [ToolCall('a', 'draft_create_deal', draft(env)),
                                    ToolCall('b', 'draft_create_deal', draft(env))]), LLMResponse('Done')])
    t = env['make'](c)
    before = n_deals(env)
    r = t.handle(REQUEST)
    made = [d for d in env['chain'].deals(env['wallet']) if d.ref == 'PO-880']
    print('duplicate', {'created': len(made), 'statuses': [d.status.name for d in made],
                        'supplier_paid_php': sum(d.down_amount for d in made) / PHP})
    assert n_deals(env) == before + 1, 'one request created and down-paid duplicate POs'


def test_model_failure_after_execution_must_not_say_nothing_was_sent(env):
    clean_plans(env)
    responses = [LLMResponse('', [ToolCall('a', 'draft_create_deal', draft(env))])]
    def fails_after_tool(*args):
        if responses:
            return responses.pop()
        raise ConnectionError('injected model outage after successful tool execution')
    t = env['make'](ScriptedLLM(fails_after_tool))
    before = n_deals(env)
    r = t.handle(REQUEST)
    print('post_execution_model_outage', {'new_deals': n_deals(env) - before, 'reply': r.reply,
                                          'executed_events': sum(e['event'] == 'executed' for e in r.events)})
    assert 'Nothing was drafted or sent' not in r.reply, 'funds moved before this false reassurance'


def test_receipt_timeout_must_leave_a_recoverable_transaction_hash(env, monkeypatch):
    clean_plans(env)
    t = env['make'](coord(('tool', 'draft_create_deal', draft(env)), ('text', 'Done')))
    eth_type = type(env['chain'].w3.eth)
    from web3.exceptions import TimeExhausted
    def timeout(self, transaction_hash, *args, **kwargs):
        raise TimeExhausted('injected RPC timeout after broadcast')
    monkeypatch.setattr(eth_type, 'wait_for_transaction_receipt', timeout)
    before = n_deals(env)
    r = t.handle(REQUEST)
    executed_or_pending = [e for e in t.audit.entries() if e['event'] in ('executed', 'tx_submitted', 'tx_pending')]
    print('receipt_timeout', {'new_deals': n_deals(env) - before, 'reply': r.reply,
                             'transaction_records': executed_or_pending})
    assert executed_or_pending, 'broadcast transaction hash was lost despite a mined new deal'


def test_negotiated_min_reserve_is_rechecked_when_owner_confirms(env, svc):
    n = agree(env, svc)
    assert svc.request_escrow(n.id)['status'] == 'needs_confirmation'
    p = n.by_id(n.agreement['proposal_id'])
    before = env['chain'].wallet_state(env['wallet']).free
    min_reserve = n.constraints.min_reserve
    # Enough funds still remain to fund escrow, but no longer to satisfy the negotiated reserve.
    amount = before - p.terms.total - min_reserve + 100 * PHP
    owner = svc.t.owner
    assert amount > 0
    assert owner._send(env['chain'].wallet(env['wallet']).functions.withdraw(owner.acct.address, amount)).ok
    r = svc.t.handle('yes')
    after = env['chain'].wallet_state(env['wallet']).free
    print('confirmation_reserve', {'reserve_php': min_reserve / PHP, 'free_after_php': after / PHP,
                                    'reply': r.reply, 'state': svc.engine.store.get(n.id).state})
    assert after >= min_reserve, 'confirmation ignored the hard buyer reserve constraint'


def test_negotiated_expiry_is_rechecked_when_owner_confirms(env, svc):
    n = agree(env, svc)
    p = n.by_id(n.agreement['proposal_id'])
    svc.engine.clock = lambda: p.expires - 1  # prepare the card immediately before agreement expiry
    assert svc.request_escrow(n.id)['status'] == 'needs_confirmation'
    # Engine clock is injectable. Payment card TTL remains fresh, agreement has expired.
    svc.engine.clock = lambda: p.expires + 1
    before = n_deals(env)
    r = svc.t.handle('yes')
    print('expired_confirmation', {'new_deals': n_deals(env) - before, 'reply': r.reply,
                                    'agreement_expired': svc.engine.now() > p.expires})
    assert n_deals(env) == before, 'fresh card executed an expired agreement'


def test_audit_log_survives_concurrent_writers(tmp_path):
    log = AuditLog(tmp_path / 'audit.jsonl')
    start = threading.Barrier(8)
    def worker(i):
        start.wait()
        for j in range(25):
            log.write('concurrent', worker=i, item=j)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(worker, range(8)))
    print('audit_concurrency', {'entries': len(log.entries()), 'count': log.count, 'verify': log.verify()})
    assert log.verify(), 'normal concurrent writes fork the hash chain'


def test_streamlit_cannot_sign_owner_commands_without_authentication(env, monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    from console import auth as authmod
    from tests.test_integration import open_lumen_deal
    import tiwala_agent.llm as llm_module
    _, did = open_lumen_deal(env)
    dep_path = tmp_path / 'deployment.json'
    dep_path.write_text(json.dumps(env['c']['dep']))
    for k, value in {'RPC_URL': env['c']['rpc'], 'AGENT_PRIVATE_KEY': env['c']['keys'][2],
                     'OWNER_PRIVATE_KEY': env['c']['keys'][1], 'TIWALA_DEPLOYMENT': str(dep_path),
                     'TIWALA_DATA': str(env['data']), 'TIWALA_AUDIT': str(tmp_path / 'streamlit-audit.jsonl'),
                     'TIWALA_ADMIN_USER': 'owner', 'TIWALA_ADMIN_PASS_HASH': authmod.hash_password('correct horse')}.items():
        monkeypatch.setenv(k, value)
    monkeypatch.setattr(llm_module, 'from_env', lambda: {'coordinator': ScriptedLLM([]),
                                                        'checker': honest_checker(), 'treasury': None})
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py'), default_timeout=30).run()
    assert not app.exception, app.exception
    assert not app.chat_input, 'an unsigned session reached the chat'
    app.text_input[0].set_value('owner')
    app.text_input[1].set_value('wrong password')
    app.button[0].click().run()
    assert not app.chat_input and 'tiwala' not in app.session_state
    assert env['chain'].deal(env['wallet'], did).status == Status.DOWN_PAID
    app.text_input[1].set_value('correct horse')
    app.button[0].click().run()
    assert not app.exception, app.exception
    app.chat_input[0].set_value(f'/attest {did}').run()
    assert env['chain'].deal(env['wallet'], did).status != Status.DOWN_PAID, 'signed-in owner could not attest'
