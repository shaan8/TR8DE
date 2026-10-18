"""Streamlit chat UI over the same Tiwala core as the CLI.

    cd agent && ../.venv/bin/streamlit run app.py

Reads ../.env if the shell has not exported it. TIWALA_DEPLOYMENT, TIWALA_DATA and TIWALA_AUDIT
override the paths; RPC_URL falls back to AGENT_RPC_URL, then the public Sepolia node.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from tiwala_agent.audit import AuditLog
from tiwala_agent.chain import Chain, OwnerConsole
from tiwala_agent.core import Tiwala, user_tz
from tiwala_agent.llm import from_env
from tiwala_agent.models import PHP, Status

HERE = Path(__file__).resolve().parent
PUBLIC_RPC = "https://ethereum-sepolia-rpc.publicnode.com"
STATUS = {
    Status.LOCKED: "Locked", Status.DOWN_PAID: "Down payment paid", Status.DELIVERED: "Delivered",
    Status.COMPLETED: "Completed", Status.REFUNDED: "Refunded", Status.DISPUTED: "Disputed",
}
OPEN = {Status.LOCKED, Status.DOWN_PAID, Status.DELIVERED, Status.DISPUTED}


def load_env() -> None:
    env = HERE.parent / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.split("#", 1)[0].strip() if not line.lstrip().startswith("#") else ""
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


CSS = """
<style>
h1, h2, h3 { letter-spacing: -0.01em; }
.tw-card { background:#272757; border:1px solid #505081; border-radius:14px; padding:14px 16px; margin-bottom:10px; }
.tw-label { color:#B9B8D6; font-size:0.78rem; text-transform:uppercase; letter-spacing:0.08em; }
.tw-value { color:#F3F3FA; font-size:1.55rem; font-weight:600; line-height:1.25; }
.tw-sub { color:#B9B8D6; font-size:0.85rem; }
.tw-bar { display:flex; height:10px; border-radius:6px; overflow:hidden; background:#505081; margin:8px 0 4px; }
.tw-free { background:#8686AC; }
.tw-locked { background:#F3F3FA; }
</style>
"""


def card(label: str, value: str, sub: str = "") -> None:
    st.markdown(f'<div class="tw-card"><div class="tw-label">{label}</div>'
                f'<div class="tw-value">{value}</div><div class="tw-sub">{sub}</div></div>',
                unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def snapshot(_t: Tiwala, version: int):
    """Chain reads for the panel. `version` bumps after every turn, so an action refreshes it at once."""
    return (_t.chain.wallet_state(_t.wallet), _t.accounts(),
            [d for d in _t.chain.deals(_t.wallet) if d.status in OPEN])


def funds_panel(t: Tiwala, version: int) -> None:
    ws, accounts, deals = snapshot(t, version)
    off = sum(a.balance for a in accounts)
    total = max(ws.free + ws.locked, 1)
    st.markdown("### Funds")
    st.markdown(
        f'<div class="tw-card"><div class="tw-label">On-chain wallet</div>'
        f'<div class="tw-value">{peso(ws.free + ws.locked)}</div>'
        f'<div class="tw-bar"><div class="tw-free" style="width:{ws.free * 100 / total:.1f}%"></div>'
        f'<div class="tw-locked" style="width:{ws.locked * 100 / total:.1f}%"></div></div>'
        f'<div class="tw-sub">Free {peso(ws.free)} · Locked in escrow {peso(ws.locked)}</div></div>',
        unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        card("Free", peso(ws.free), "the agent can lock this")
    with c2:
        card("Locked", peso(ws.locked), "held for open deals")
    card("Connected accounts (read-only)", peso(off),
         " · ".join(f"{a.provider} {peso(a.balance)}" for a in accounts) or "none consented")
    card("Agent daily limit left", peso(ws.daily_remaining),
         f"per deal up to {peso(ws.per_deal_cap)} · paused" if ws.paused else f"per deal up to {peso(ws.per_deal_cap)}")
    if ws.underfunded:
        st.error("Wallet is underfunded: every money-moving action is halted.")

    names = t.names()
    st.markdown("### Open deals")
    if not deals:
        st.caption("No open deals.")
    tz = user_tz()
    for d in deals:
        due = datetime.fromtimestamp(d.deadline, tz).strftime("%b %d, %H:%M")
        st.markdown(
            f'<div class="tw-card"><div class="tw-label">Deal {d.id} · {STATUS[d.status]}</div>'
            f'<div class="tw-value" style="font-size:1.1rem">{names.get(d.supplier, d.supplier[:10])}</div>'
            f'<div class="tw-sub">{peso(d.total)} · {d.down_bps / 100:g}% down · unpaid {peso(d.unpaid)}'
            f' · due {due}</div></div>', unsafe_allow_html=True)
    st.caption(f"[Wallet on Etherscan](https://sepolia.etherscan.io/address/{t.wallet})")


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
        st.session_state.chat = []
        st.session_state.version = 0
    t: Tiwala = st.session_state.tiwala
    audit: AuditLog = st.session_state.audit
    chat: list[tuple[str, str]] = st.session_state.chat

    left, right = st.columns([5, 3], gap="large")
    with left:
        st.title("Tiwala")
        st.caption("AI escrow agent · sees all your money, spends only what sits in escrow · Sepolia · "
                   f"LLM: {os.environ.get('TIWALA_LLM_PROVIDER', 'deepseek')}")
        b1, b2, _ = st.columns([1, 1, 3])
        cmd = None
        if b1.button("Run monitor", help="/tick: check deadlines, attestations and balances now"):
            cmd = "/tick"
        if b2.button("Verify audit log", help="/verify: recompute the hash chain"):
            cmd = "/verify"
        for role, text in chat:
            with st.chat_message(role, avatar="🧑" if role == "user" else "🤝"):
                st.markdown(text)
        msg = st.chat_input("Ask Tiwala, or type /attest N, /approve N, /dispute N, /resolve N release|refund")
        msg = cmd or msg
        if msg:
            chat.append(("user", msg))
            with st.chat_message("user", avatar="🧑"):
                st.markdown(msg)
            with st.chat_message("assistant", avatar="🤝"):
                with st.spinner("Thinking"):
                    if msg == "/tick":
                        reply = "\n\n".join(t.tick()) or "Monitor: nothing to do."
                    elif msg == "/verify":
                        reply = "Audit chain intact." if audit.verify() else "AUDIT CHAIN BROKEN."
                    else:
                        reply = t.handle(msg).reply
                st.markdown(reply)
            chat.append(("assistant", reply))
            st.session_state.version += 1
            st.rerun()

    with right:
        try:
            funds_panel(t, st.session_state.version)
        except Exception as e:  # RPC hiccup: keep the chat usable
            st.warning(f"Could not read the chain: {e}")


main()
