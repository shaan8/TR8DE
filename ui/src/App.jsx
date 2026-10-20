import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { FileWarning, ShieldAlert, ShieldCheck } from "lucide-react";
import { Composer, EmptyChat, SUGGESTIONS, Suggestions, Turn } from "./components/Chat.jsx";
import { NeedsYou } from "./components/Feed.jsx";
import { Shell } from "./components/Shell.jsx";
import { Treasury, openDeals } from "./components/Sidebar.jsx";
import { Chip } from "./components/ui.jsx";
import { getJSON, postJSON, query, sendMessage, setExplorer } from "./lib.js";

function StatePicker({ fixture, list }) {
  if (!list.length) return null;
  return (
    <label className="flex items-center gap-2 text-micro text-ink-2">
      <span>Screen state</span>
      <select value={fixture || ""} className="min-h-[32px] max-w-[200px] rounded-md border border-subtle bg-raised px-2 text-cap text-ink"
        onChange={(e) => { const p = new URLSearchParams(window.location.search); e.target.value ? p.set("fixture", e.target.value) : p.delete("fixture"); window.location.search = p; }}>
        <option value="">Live agent</option>
        {list.map((f) => <option key={f.name} value={f.name}>{f.n}. {f.title}{f.synthetic ? " (synthetic)" : ""}</option>)}
      </select>
    </label>
  );
}

export default function App() {
  const fixture = query();
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);
  const [turns, setTurns] = useState([]);
  const [activity, setActivity] = useState([]);
  const [pendingLine, setPendingLine] = useState(null);
  const [pendingPayeeLine, setPendingPayeeLine] = useState(null);
  const [confirmedLines, setConfirmed] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [audit, setAudit] = useState(null);
  const [list, setList] = useState([]);
  const inputRef = useRef(null);
  const threadRef = useRef(null);
  // Like any chat: open on the latest message, and follow new steps as they stream in.
  const lastEvents = turns.length ? turns[turns.length - 1].events.length : 0;
  useLayoutEffect(() => {
    const el = threadRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns.length, lastEvents, !!state]);

  // Live refreshes keep the chat: /api/state has no conversation history, only wallet and deals.
  const load = async (initial = false) => {
    try {
      const s = await getJSON("/api/state", fixture);
      setExplorer(s.explorer); setState(s); setActivity(s.activity);
      if (initial) { setTurns(s.turns); setPendingLine(s.pending?.line ?? null); setPendingPayeeLine(s.pending_payee_line ?? null); }
    } catch (e) { setError(String(e.message || e)); }
  };
  useEffect(() => {
    load(true);
    getJSON("/api/verify", fixture).then(setAudit).catch(() => setAudit(null));
    getJSON("/api/fixtures").then(setList).catch(() => {});
  }, []);

  const pendingCard = useMemo(() => {
    if (pendingLine == null) return state?.pending?.card ? state.pending : null;
    for (const t of turns) for (const e of t.events) if (e.line === pendingLine) return { card: e.card };
    return null;
  }, [turns, pendingLine, state]);

  if (error) return <main className="p-6 text-bad">Could not load the console: {error}. Is the API running on :8000?</main>;
  if (!state) return <main className="p-6 text-ink-2" aria-busy="true">Loading the console…</main>;
  const view = new URLSearchParams(window.location.search).get("view");

  const halted = state.wallet.underfunded || state.wallet.paused;
  const ownerWords = turns.map((t) => t.user).filter((u) => u && !u.startsWith("/"));
  const savedPayees = new Set(turns.flatMap((t) => t.events.filter((e) => e.event === "payee_saved").map((e) => e.address)));
  const payeeDraft = pendingPayeeLine != null && turns.flatMap((t) => t.events).find((e) => e.line === pendingPayeeLine);

  const send = async (text) => {
    setBusy(true); setDraft(""); setPendingPayeeLine(null);  // any other message drops a drafted payee
    const idx = turns.length;
    setTurns((ts) => [...ts, { user: text, reply: "", events: [], inflight: true }]);
    try {
      const res = await sendMessage(text, fixture, (step) =>
        setTurns((ts) => ts.map((t, i) => (i === idx ? { ...t, events: [...t.events, step] } : t))));
      const t = { ...res.turn, user: text, source: fixture ? `${res.turn.source} (replayed)` : null, inflight: false };
      setTurns((ts) => ts.map((x, i) => (i === idx ? t : x)));
      const v = t.events.filter((e) => e.event === "verdict" && e.verdict.allowed && e.verdict.needs_confirmation).pop();
      setPendingLine(v ? v.line : null);
      const p = t.events.filter((e) => e.event === "payee_check" && e.allowed).pop();
      setPendingPayeeLine(p ? p.line : null);
      if (!fixture) load();
    } catch (e) {
      setTurns((ts) => ts.map((t, i) => (i === idx ? { ...t, inflight: false, reply: `Could not reach the agent: ${e.message}. Nothing was sent.` } : t)));
    } finally { setBusy(false); }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      const { turn } = await postJSON("/api/confirm", fixture, { card_id: pendingCard?.card?.id });
      setConfirmed((s) => new Set([...s, pendingLine]));
      setPendingLine(null);
      setTurns((ts) => [...ts, turn]);
      if (!fixture) load();
    } finally { setBusy(false); }
  };

  const confirmPayee = async (code) => {
    setBusy(true);
    try {
      const { turn } = await postJSON("/api/confirm", fixture, { code });
      setPendingPayeeLine(null);
      setTurns((ts) => [...ts, turn]);
      if (!fixture) load();
    } finally { setBusy(false); }
  };

  const tick = async () => {
    setBusy(true);
    try {
      const r = await postJSON("/api/tick", fixture);
      if (fixture) setActivity(r.activity); else load();
    } finally { setBusy(false); }
  };

  const ctx = {
    pendingLine, confirmedLines, halted, busy, ownerWords, pendingPayeeLine, savedPayees, now: state.now,
    onConfirm: confirm, onConfirmPayee: confirmPayee,
    onEdit: () => { setDraft("Change it to "); inputRef.current?.focus(); },
    onRetry: (text) => text && send(text),
  };

  const network = state?.network || "Sepolia testnet";
  const actions = (
    <>
      {fixture && <Chip tone="accent">Fixture {state.state_no}: {state.title}</Chip>}
      {state.synthetic && <Chip tone="warn" icon={FileWarning}>Synthetic fixture</Chip>}
      {audit && (audit.intact ? <Chip tone="ok" icon={ShieldCheck}>Audit chain intact · {audit.entries} entries</Chip>
        : <Chip tone="bad" icon={ShieldAlert}>Audit chain broken</Chip>)}
      <StatePicker fixture={fixture} list={list} />
    </>
  );
  const tab = view === "payments" ? "deals" : state.highlight === "payees" ? "payees" : "activity";
  return (
    <Shell active={view === "payments" ? "payments" : ""} crumb={view === "payments" ? "Payments" : "Agent workspace"} actions={actions}
      prompts={SUGGESTIONS} onPrompt={(p) => { setDraft(p); inputRef.current?.focus(); }}
      status={fixture ? `Replayed from ${state.audit_source || "audit log"} · no model or chain calls` : `Live · ${network} and the configured model`}
      counts={{ payments: openDeals(state.deals).length }}
      canvas={<Treasury key={tab} state={state} activity={activity} initialTab={tab} highlightFeed={state.highlight === "feed"} />}>
      <main className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-end justify-between gap-3 px-4 pb-4 pt-6 md:px-9">
          <div><p className="text-micro tracking-[0.14em] text-ink-2">SUPPLIER PAYMENTS</p>
            <h2 className="mt-2 font-display text-title font-semibold tracking-[-0.02em]">Payments chat</h2></div>
        </div>
        {halted && (
          <div role="alert" className="mx-4 mb-4 flex items-start gap-3 rounded-md border border-bad/60 bg-[#2b1c18] p-3.5 md:mx-9">
            <ShieldAlert className="mt-0.5 shrink-0 text-bad" size={18} aria-hidden="true" />
            <div>
              <p className="text-sm font-semibold text-bad">{state.wallet.paused ? "Wallet paused by the owner" : "Halted: the escrow wallet is underfunded"}</p>
              <p className="text-cap text-ink-2">{state.wallet.paused ? "Money-moving actions are blocked. Type /unfreeze to resume. Owner commands and reading still work." : "Money-moving actions are blocked until the balance covers open deals. Owner commands and reading still work."}</p>
            </div>
          </div>
        )}
        <NeedsYou pending={pendingCard} payee={payeeDraft || null} alerts={state.alerts} highlight={state.highlight === "needs"}
          onReview={(id = "pending-card") => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" })} />
        <section ref={threadRef} aria-label="Conversation" className="relative min-h-0 flex-1 space-y-8 overflow-y-auto px-4 pb-6 pt-5 md:px-9">
          {turns.length ? turns.map((t, i) => <Turn key={i} turn={t} ctx={ctx} />) : <EmptyChat />}
        </section>
        <div className="bg-gradient-to-t from-canvas from-85% to-transparent px-4 pb-4 pt-4 md:px-8">
          <Suggestions disabled={busy} onSend={send} onPick={(s) => { setDraft(s); inputRef.current?.focus(); }} />
          <Composer busy={busy} value={draft} setValue={setDraft} onSend={send} onTick={tick} inputRef={inputRef}
            model={state.agents?.coordinator && state.agents.coordinator !== "off" ? `Coordinator · ${state.agents.coordinator}` : "Coordinator"} />
          <p className="mx-0.5 mt-2.5 flex justify-between gap-3 text-micro text-ink-2">Your intent. Checked at every step.
            <span className="hidden sm:inline">{fixture ? "Replayed · no funds move" : "Money moves only through on-chain escrow"}</span></p>
        </div>
      </main>
    </Shell>
  );
}
