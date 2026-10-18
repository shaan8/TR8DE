"""Streamlit agent console over the same Tiwala core as the CLI.

    cd agent && ../.venv/bin/streamlit run app.py

Reads ../.env if the shell has not exported it. TIWALA_DEPLOYMENT, TIWALA_DATA and TIWALA_AUDIT
override the paths; RPC_URL falls back to AGENT_RPC_URL, then the public Sepolia node.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from html import escape
from pathlib import Path

import streamlit as st

from tiwala_agent.audit import AuditLog
from tiwala_agent.chain import Chain, OwnerConsole
from tiwala_agent.core import Tiwala, user_tz
from tiwala_agent.llm import from_env
from tiwala_agent.models import PHP, Status

HERE = Path(__file__).resolve().parent
PUBLIC_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
TX_URL = "https://sepolia.etherscan.io/tx/"
STATUS = {
    Status.LOCKED: "Locked", Status.DOWN_PAID: "Down payment paid", Status.DELIVERED: "Delivered",
    Status.COMPLETED: "Completed", Status.REFUNDED: "Refunded", Status.DISPUTED: "Disputed",
}
OPEN = {Status.LOCKED, Status.DOWN_PAID, Status.DELIVERED, Status.DISPUTED}

# Blue eclipse: #0F0E47 night, #272757 deep, #505081 mid, #8686AC haze. Light canvas so the four read apart.
CSS = """
<style>
.stApp { background:#F5F5FA; }
[data-testid="stSidebar"] { background:#0F0E47; }
[data-testid="stSidebar"] * { color:#E4E4F1; }
[data-testid="stSidebar"] a { color:#B9B8E0 !important; }
.block-container { padding-top:2rem; max-width:1100px; }
.tw-head { background:#272757; border-radius:18px; padding:22px 26px; display:flex; justify-content:space-between;
  align-items:center; margin-bottom:18px; }
.tw-brand { color:#F5F5FA; font-size:1.9rem; font-weight:700; letter-spacing:-0.01em; }
.tw-tag { color:#B9B8D6; font-size:0.92rem; margin-top:2px; }
.tw-chips { display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.tw-chip { background:#505081; color:#F5F5FA; border-radius:999px; padding:5px 12px; font-size:0.8rem; white-space:nowrap; }
.tw-chip.live::before { content:""; display:inline-block; width:8px; height:8px; border-radius:50%; background:#9BE3B5;
  margin-right:7px; vertical-align:middle; }
.tw-pending { background:#FFFFFF; border:2px solid #505081; border-radius:14px; padding:14px 18px; margin:8px 0 4px;
  color:#0F0E47; }
.tw-pending b { color:#505081; }
[data-testid="stChatMessage"] { background:#FFFFFF; border:1px solid #DCDCEA; border-radius:14px; padding:14px 16px; }
.tw-trace { border-left:2px solid #DCDCEA; margin:6px 0 2px 6px; padding-left:16px; }
.tw-step { position:relative; margin:0 0 10px 0; font-size:0.88rem; color:#272757; line-height:1.4; }
.tw-step::before { content:""; position:absolute; left:-23px; top:5px; width:12px; height:12px; border-radius:50%;
  background:var(--dot); border:2px solid #F5F5FA; }
.tw-who { font-weight:600; color:#0F0E47; }
.tw-ok { color:#2E7D5B; font-weight:600; }
.tw-bad { color:#B3261E; font-weight:600; }
.tw-muted { color:#6E6D96; }
.tw-legend { font-size:0.78rem; color:#6E6D96; margin-top:4px; }
.tw-legend span { display:inline-block; width:9px; height:9px; border-radius:50%; margin:0 5px 0 12px; vertical-align:middle; }
.tw-card { background:#272757; border-radius:12px; padding:12px 14px; margin-bottom:10px; }
.tw-label { color:#8686AC !important; font-size:0.72rem; text-transform:uppercase; letter-spacing:0.09em; }
.tw-value { color:#F5F5FA !important; font-size:1.35rem; font-weight:650; line-height:1.25; }
.tw-sub { color:#B9B8D6 !important; font-size:0.8rem; }
.tw-bar { display:flex; height:8px; border-radius:6px; overflow:hidden; background:#505081; margin:8px 0 6px; }
.tw-free { background:#8686AC; }
.tw-locked { background:#F5F5FA; }
</style>
"""

LLM_DOT, CODE_DOT, CHAIN_DOT, OWNER_DOT = "#8686AC", "#505081", "#0F0E47", "#2E7D5B"


def load_env() -> None:
    env = HERE.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = "" if line.lstrip().startswith("#") else line.split("#", 1)[0].strip()
            if "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    os.environ.setdefault("RPC_URL", os.environ.get("AGENT_RPC_URL") or PUBLIC_RPC)
    if not os.environ.get("DEEPSEEK_API_KEY") and os.environ.get("OPENROUTER_API_KEY"):
        os.environ.setdefault("TIWALA_LLM_PROVIDER", "openrouter")


def peso(units: int) -> str:
    return f"₱{units / PHP:,.0f}"


def build() -> tuple[Tiwala, AuditLog, dict]:
    dep_path = Path(os.environ.get("TIWALA_DEPLOYMENT", HERE.parent / "deployments" / "11155111.json"))
    dep = json.loads(dep_path.read_text())
    chain = Chain(os.environ["RPC_URL"], dep, os.environ["AGENT_PRIVATE_KEY"])
    owner = OwnerConsole(chain, dep["demoWallet"], os.environ["OWNER_PRIVATE_KEY"]) \
        if os.environ.get("OWNER_PRIVATE_KEY") else None
    audit = AuditLog(os.environ.get("TIWALA_AUDIT", str(HERE / "logs" / "audit.jsonl")))
    data = os.environ.get("TIWALA_DATA", str(HERE / "data"))
    return Tiwala(chain, dep["demoWallet"], data, from_env(), audit, owner), audit, dep


# ------------------------------------------------------------------ agent trace

def _tx(h: str | None) -> str:
    return f'<a href="{TX_URL}{escape(h)}" target="_blank">{escape(h[:10])}…</a>' if h else ""


def _step(dot: str, who: str, body: str) -> str:
    return f'<div class="tw-step" style="--dot:{dot}"><span class="tw-who">{escape(who)}</span> · {body}</div>'


def trace_html(events: list[dict]) -> str:
    """One line per pipeline step, coloured by who acted: LLM agent, deterministic code, chain, owner."""
    out = []
    for e in events:
        k = e.get("event")
        if k == "user_message":
            flags = e.get("flags") or []
            out.append(_step(CODE_DOT, "Input guard", '<span class="tw-bad">flagged: ' + escape(", ".join(flags)) +
                             "</span>" if flags else '<span class="tw-ok">clean</span>, tagged as owner input'))
        elif k == "tool_call":
            args = ", ".join(f"{a}={v}" for a, v in (e.get("args") or {}).items())
            out.append(_step(LLM_DOT, "Coordinator", f"called <code>{escape(e.get('name', ''))}({escape(args)})</code>"))
        elif k == "verdict":
            view, intent, chk, v = e.get("view", {}), e.get("intent", {}), e.get("checker", {}), e.get("verdict", {})
            what = escape(f"{view.get('kind', '').replace('_', ' ')} · {view.get('supplier', '')}")
            out.append(_step(LLM_DOT, "Coordinator", f"drafted <b>{what}</b>"))
            mm = intent.get("mismatches") or []
            out.append(_step(CODE_DOT, "Intent verifier", '<span class="tw-ok">matches your words</span>' if intent.get("ok")
                             else '<span class="tw-bad">mismatch: ' + escape("; ".join(mm)) + "</span>"))
            out.append(_step(LLM_DOT, "Checker", ('<span class="tw-ok">approved</span>' if chk.get("approve")
                             else '<span class="tw-bad">rejected</span>') +
                             f' <span class="tw-muted">{escape(chk.get("reason") or "")}</span>'))
            tier = v.get("tier")
            res = ('<span class="tw-bad">refused</span>' if not v.get("allowed") else
                   "needs your confirmation" if v.get("needs_confirmation") else '<span class="tw-ok">allowed</span>')
            extra = "; ".join((v.get("reasons") or []) + [f"flag: {f}" for f in v.get("flags") or []])
            out.append(_step(CODE_DOT, "Policy engine", f"Tier {tier} · {res}" +
                             (f' <span class="tw-muted">{escape(extra)}</span>' if extra else "")))
        elif k == "confirmed":
            out.append(_step(OWNER_DOT, "Owner", "confirmed in their own words"))
        elif k == "executed":
            deal = f" · deal {e['deal_id']}" if e.get("deal_id") else ""
            out.append(_step(CHAIN_DOT, "Gate + signer", f'authorized, simulated, sent {_tx(e.get("tx"))}{deal}'))
        elif k == "tx_failed":
            out.append(_step(CHAIN_DOT, "Contract", f'<span class="tw-bad">reverted</span> {escape(str(e.get("error")))}'))
        elif k == "owner_command":
            ok = '<span class="tw-ok">sent</span>' if e.get("ok") else f'<span class="tw-bad">{escape(str(e.get("error")))}</span>'
            out.append(_step(OWNER_DOT, "Owner key", f'{escape(e.get("command", ""))} {ok} {_tx(e.get("tx"))}'))
        elif k == "coordinator_error":
            out.append(_step(LLM_DOT, "Coordinator", f'<span class="tw-bad">unavailable</span> '
                                                     f'<span class="tw-muted">{escape(str(e.get("error"))[:160])}</span>'))
        elif k == "monitor_tick":
            out.append(_step(CODE_DOT, "Monitor tick", f'{len(e.get("notes") or [])} note(s)'))
        elif k == "monitor_halt":
            out.append(_step(CODE_DOT, "Monitor tick", '<span class="tw-bad">halted: wallet underfunded</span>'))
    return '<div class="tw-trace">' + "".join(out) + "</div>" if out else ""


LEGEND = ('<div class="tw-legend">Who acted:'
          f'<span style="background:{LLM_DOT}"></span>LLM agent<span style="background:{CODE_DOT}"></span>code guard'
          f'<span style="background:{CHAIN_DOT}"></span>chain<span style="background:{OWNER_DOT}"></span>owner</div>')


# ------------------------------------------------------------------ wallet sidebar

@st.cache_data(ttl=60, show_spinner=False)
def snapshot(_t: Tiwala, version: int):
    """Chain reads for the sidebar. `version` bumps after every turn, so an action refreshes it at once."""
    return (_t.chain.wallet_state(_t.wallet), _t.accounts(),
            [d for d in _t.chain.deals(_t.wallet) if d.status in OPEN])


def card(label: str, value: str, sub: str = "", extra: str = "") -> None:
    st.markdown(f'<div class="tw-card"><div class="tw-label">{label}</div><div class="tw-value">{value}</div>'
                f'{extra}<div class="tw-sub">{sub}</div></div>', unsafe_allow_html=True)


def wallet_sidebar(t: Tiwala, version: int) -> None:
    ws, accounts, deals = snapshot(t, version)
    total = max(ws.free + ws.locked, 1)
    st.markdown("#### Wallet")
    bar = (f'<div class="tw-bar"><div class="tw-free" style="width:{ws.free * 100 / total:.1f}%"></div>'
           f'<div class="tw-locked" style="width:{ws.locked * 100 / total:.1f}%"></div></div>')
    card("On-chain escrow wallet", peso(ws.free + ws.locked),
         f"Free {peso(ws.free)} · Locked {peso(ws.locked)}", bar)
    card("Connected accounts · read-only", peso(sum(a.balance for a in accounts)),
         " · ".join(f"{a.provider} {peso(a.balance)}" for a in accounts) or "none consented")
    card("Agent daily limit left", peso(ws.daily_remaining),
         ("PAUSED · " if ws.paused else "") + f"per deal up to {peso(ws.per_deal_cap)}")
    if ws.underfunded:
        st.error("Underfunded: every money-moving action is halted.")
    st.markdown("#### Open deals")
    if not deals:
        st.caption("No open deals.")
    names, tz = t.names(), user_tz()
    for d in deals:
        due = datetime.fromtimestamp(d.deadline, tz).strftime("%b %d, %H:%M")
        card(f"Deal {d.id} · {STATUS[d.status]}", escape(names.get(d.supplier, d.supplier[:10])),
             f"{peso(d.total)} · {d.down_bps / 100:g}% down · due {due}")
    st.markdown(f"[Wallet on Etherscan](https://sepolia.etherscan.io/address/{t.wallet})")


# ------------------------------------------------------------------ app

def run_turn(t: Tiwala, audit: AuditLog, msg: str) -> tuple[str, list[dict]]:
    if msg == "/tick":
        t._events = []
        notes = t.tick()
        return "\n\n".join(notes) or "Monitor: nothing to do.", list(t._events)
    if msg == "/verify":
        return ("Audit chain intact." if audit.verify() else "AUDIT CHAIN BROKEN."), []
    r = t.handle(msg)
    return r.reply, r.events


def main() -> None:
    st.set_page_config(page_title="Tiwala", page_icon="🤝", layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    load_env()
    if "tiwala" not in st.session_state:
        try:
            st.session_state.tiwala, st.session_state.audit, st.session_state.dep = build()
        except KeyError as e:
            st.error(f"Missing {e.args[0]} in the environment or ../.env.")
            st.stop()
        st.session_state.chat, st.session_state.version = [], 0
    t: Tiwala = st.session_state.tiwala
    audit: AuditLog = st.session_state.audit
    chat: list[tuple[str, str, list]] = st.session_state.chat

    provider = os.environ.get("TIWALA_LLM_PROVIDER", "deepseek")
    st.markdown(
        '<div class="tw-head"><div><div class="tw-brand">Tiwala</div>'
        '<div class="tw-tag">Escrow agent for supplier payments · sees all your money, spends only what sits in escrow</div></div>'
        f'<div class="tw-chips"><span class="tw-chip live">Agent online</span><span class="tw-chip">Sepolia</span>'
        f'<span class="tw-chip">LLM: {escape(provider)}</span><span class="tw-chip">Wallet {t.wallet[:6]}…{t.wallet[-4:]}</span>'
        '</div></div>', unsafe_allow_html=True)

    with st.sidebar:
        try:
            wallet_sidebar(t, st.session_state.version)
        except Exception as e:  # RPC hiccup: keep the chat usable
            st.warning(f"Could not read the chain: {e}")

    b1, b2, _ = st.columns([1, 1, 4])
    cmd = None
    if b1.button("Run monitor", help="/tick: check deadlines, attestations and balances now", use_container_width=True):
        cmd = "/tick"
    if b2.button("Verify audit log", help="/verify: recompute the hash chain", use_container_width=True):
        cmd = "/verify"
    st.markdown(LEGEND, unsafe_allow_html=True)

    for i, (role, text, events) in enumerate(chat):
        with st.chat_message(role, avatar="🧑" if role == "user" else "🤝"):
            st.markdown(text)
            if events:
                with st.expander("Agent trace", expanded=i == len(chat) - 1):
                    st.markdown(trace_html(events), unsafe_allow_html=True)

    if t.pending:
        st.markdown('<div class="tw-pending"><b>Waiting for you.</b> The agent drafted an action that needs your '
                    'confirmation. Nothing moves until you say yes.</div>', unsafe_allow_html=True)
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("Yes, confirm", type="primary", use_container_width=True):
            cmd = "yes"
        if c2.button("Cancel", use_container_width=True):
            t.pending = None
            st.rerun()

    msg = st.chat_input("Ask Tiwala, or type /attest N, /approve N, /dispute N, /resolve N release|refund")
    msg = cmd or msg
    if msg:
        chat.append(("user", msg, []))
        with st.chat_message("user", avatar="🧑"):
            st.markdown(msg)
        with st.chat_message("assistant", avatar="🤝"):
            with st.status("Coordinator, Checker and policy engine at work…", expanded=False):
                reply, events = run_turn(t, audit, msg)
            st.markdown(reply)
        chat.append(("assistant", reply, events))
        st.session_state.version += 1
        st.rerun()


main()
