"""Probes from the third external audit (20 October 2026) of 27f5196, formerly a61a4ff (SECURITY.md). Each failed on that commit.
Local Anvil chain and scripted models only."""
import json
import pytest
from tests.conftest import chain_env  # noqa: F401
from tests.test_integration import env, coord, day, n_deals
from tests.test_negotiation_chain import svc, agree
from tiwala_agent.llm import ScriptedLLM, LLMResponse, ToolCall
from tiwala_agent.models import PHP
from tiwala_agent.negotiation import NegotiationError

def clean(env):
    (env['data'] / 'plans.json').write_text(json.dumps({'buffer':0,'inflows':[],'planned':[]}))

def fields(env, ref='PO-880', total=10000):
    return {'supplier':'Lumen Textiles','total_php':total,'down_pct':10,'deadline':day(env['chain'],10),'po_ref':ref}

def request(ref='PO-880', total=10000):
    return f'Create escrow for Lumen {ref}, PHP {total}, 10% down, delivery in 10 days'

def test_read_question_must_not_create_model_invented_deal(env):
    clean(env)
    t=env['make'](coord(('tool','draft_create_deal',fields(env)),('text','Done')))
    before=n_deals(env)
    r=t.handle('What is the delivery record of Lumen Textiles?')
    made=[d for d in env['chain'].deals(env['wallet']) if d.ref=='PO-880']
    print('READ_QUESTION',{'new_deals':n_deals(env)-before,'states':[d.status.name for d in made],
        'paid_php':sum(d.down_amount for d in made)/PHP,
        'verdicts':[e['verdict'] for e in r.events if e['event']=='verdict']})
    assert n_deals(env)==before, 'read question authorized a model-invented deal'

def test_stale_card_confirmation_must_not_approve_replacement(env,monkeypatch):
    clean(env)
    t=env['make'](coord(('tool','draft_create_deal',fields(env)),('text','A'),
        ('tool','draft_create_deal',fields(env,'PO-881',20000)),('text','B')))
    ws=env['chain'].wallet_state(env['wallet'])
    (env['data'] / 'plans.json').write_text(json.dumps({'buffer':ws.free,'inflows':[],'planned':[]}))
    card_a=t.handle(request()).reply
    assert t.pending.action.ref=='PO-880'
    t.handle(request('PO-881',20000))
    assert t.pending.action.ref=='PO-881'
    from console import server
    monkeypatch.setattr(server,'_live',t)
    reply=server.confirm(body=None,fixture=None)
    made=[d for d in env['chain'].deals(env['wallet']) if d.ref in ('PO-880','PO-881')]
    print('STALE_CARD',{'displayed_ref':'PO-880','created':[(d.ref,d.total/PHP,d.status.name) for d in made],
        'reply':reply['turn']['reply']})
    assert not any(d.ref=='PO-881' for d in made), 'generic confirm approved a different card'

def test_declining_escrow_must_allow_negotiation_to_close(env,svc):
    n=agree(env,svc)
    assert svc.request_escrow(n.id)['status']=='needs_confirmation'
    svc.t.handle('no, cancel that')
    assert svc.t.pending is None
    try:
        result=svc.engine.owner_close(n.id,cancel=True).state
    except NegotiationError as e:
        result=str(e)
    print('DECLINE',{'pending':svc.t.pending,'state':svc.engine.store.get(n.id).state,'close_result':result})
    assert result=='cancelled', 'declined card left negotiation trapped in ready_for_escrow'

def test_pending_create_must_not_be_broadcast_again(env,monkeypatch):
    clean(env)
    t=env['make'](coord(('tool','draft_create_deal',fields(env)),('text','Done'),
        ('tool','draft_create_deal',fields(env)),('text','Done')))
    import tiwala_agent.chain as cm
    monkeypatch.setattr(cm,'_await',lambda w,h:(None,'injected receipt timeout'))
    before=n_deals(env)
    env['w3'].provider.make_request('evm_setAutomine',[False])
    try:
        a=t.handle(request())
        b=t.handle(request())
    finally:
        env['w3'].provider.make_request('evm_setAutomine',[True])
        env['w3'].provider.make_request('evm_mine',[])
    made=[d for d in env['chain'].deals(env['wallet']) if d.ref=='PO-880']
    hashes=[e['tx'] for r in (a,b) for e in r.events if e['event']=='tx_pending']
    print('PENDING_RETRY',{'tx_hashes':hashes,'new_deals':n_deals(env)-before,
        'locked_php':sum(d.total for d in made)/PHP,'replies':[a.reply,b.reply]})
    assert len(made)<=1, 'two pending transactions created duplicate escrow for one PO'

def test_step_limit_must_report_already_sent_payment(env):
    clean(env)
    steps=[LLMResponse('',[ToolCall('create','draft_create_deal',fields(env))])]
    steps += [LLMResponse('',[ToolCall(str(i),'get_overview',{})]) for i in range(7)]
    t=env['make'](ScriptedLLM(steps))
    r=t.handle(request())
    print('STEP_LIMIT',{'reply':r.reply,'executed':sum(e['event']=='executed' for e in r.events)})
    assert 'Nothing was paid' not in r.reply, 'false reassurance after successful deposit'

def test_past_inflow_must_not_inflate_current_balance():
    from tiwala_agent.forecast import Flow,with_new_deal
    f=with_new_deal(10000,[Flow(99,10000,'already received')],[],0,100,15000,101)
    print('PAST_INFLOW',f)
    assert not f.ok, 'historical inflow counted again on top of current on-chain balance'


def test_owner_stated_in_budget_deal_still_runs_on_its_own(env):
    """The fix above must not cost the autonomy: all four terms in the owner's words, inside the contract's
    approvalThreshold, creates the deal and pays the deposit with no card and no yes."""
    clean(env)
    t = env['make'](coord(('tool', 'draft_create_deal', fields(env)), ('text', 'Done')))
    before = n_deals(env)
    r = t.handle(request())
    made = [d for d in env['chain'].deals(env['wallet']) if d.ref == 'PO-880']
    assert t.pending is None and n_deals(env) == before + 1
    assert made[0].status.name == 'DOWN_PAID', r.reply
