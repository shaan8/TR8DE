import { useEffect, useMemo, useRef, useState } from "react";
import { FileWarning, ShieldAlert, ShieldCheck } from "lucide-react";
import { Composer, EmptyChat, Turn } from "./components/Chat.jsx";
import { Feed, NeedsYou } from "./components/Feed.jsx";
import { DailyLimit, Deals, Suppliers, Wallet } from "./components/Sidebar.jsx";
import { Chip } from "./components/ui.jsx";
import { getJSON, postJSON, query, sendMessage } from "./lib.js";

function StatePicker({ fixture, list }) {
  if (!list.length) return null;
  return (
    <label className="flex items-center gap-2 text-sm text-ink-2">
      <span>Screen state</span>
      <select value={fixture || ""} className="min-h-[36px] max-w-[220px] rounded border border-accent bg-raised px-2 text-ink"
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
  const [confirmedLines, setConfirmed] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [audit, setAudit] = useState(null);
  const [list, setList] = useState([]);
  const inputRef = useRef(null);

  // Live refreshes keep the chat: /api/state has no conversation history, only wallet and deals.
  const load = async (initial = false) => {
    try {
      const s = await getJSON("/api/state", fixture);
      setState(s); setActivity(s.activity);
      if (initial) { setTurns(s.turns); setPendingLine(s.pending?.line ?? null); }
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

  const halted = state.wallet.underfunded || state.wallet.paused;
  const ownerWords = turns.map((t) => t.user).filter((u) => u && !u.startsWith("/"));

  const send = async (text) => {
    setBusy(true); setDraft("");
    const idx = turns.length;
    setTurns((ts) => [...ts, { user: text, reply: "", events: [], inflight: true }]);
    try {
      const res = await sendMessage(text, fixture, (step) =>
        setTurns((ts) => ts.map((t, i) => (i === idx ? { ...t, events: [...t.events, step] } : t))));
      const t = { ...res.turn, user: text, source: fixture ? `${res.turn.source} (replayed)` : null, inflight: false };
      setTurns((ts) => ts.map((x, i) => (i === idx ? t : x)));
      const v = t.events.filter((e) => e.event === "verdict" && e.verdict.allowed && e.verdict.needs_confirmation).pop();
      setPendingLine(v ? v.line : null);
      if (!fixture) load();
    } catch (e) {
      setTurns((ts) => ts.map((t, i) => (i === idx ? { ...t, inflight: false, reply: `Could not reach the agent: ${e.message}. Nothing was sent.` } : t)));
    } finally { setBusy(false); }
  };

  const confirm = async () => {
    setBusy(true);
    try {
      const { turn } = await postJSON("/api/confirm", fixture);
      setConfirmed((s) => new Set([...s, pendingLine]));
      setPendingLine(null);
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
    pendingLine, confirmedLines, halted, busy, ownerWords,
    onConfirm: confirm,
    onEdit: () => { setDraft("Change it to "); inputRef.current?.focus(); },
    onRetry: (text) => text && send(text),
  };

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-4 lg:px-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-section font-bold tracking-tight">Tiwala</h1>
          <p className="text-sm text-ink-2">Escrow agent for your supplier payments · Sepolia testnet</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {fixture && <Chip tone="accent">Fixture {state.state_no}: {state.title}</Chip>}
          {state.synthetic && <Chip tone="warn" icon={FileWarning}>Synthetic fixture</Chip>}
          {audit && (audit.intact ? <Chip tone="ok" icon={ShieldCheck}>Audit chain intact · {audit.entries} entries</Chip>
            : <Chip tone="bad" icon={ShieldAlert}>Audit chain broken</Chip>)}
          <StatePicker fixture={fixture} list={list} />
        </div>
      </header>

      {halted && (
        <div role="alert" className="mb-4 flex items-start gap-3 rounded border-2 border-bad bg-raised p-4">
          <ShieldAlert className="mt-0.5 shrink-0 text-bad" aria-hidden="true" />
          <div>
            <p className="font-semibold text-bad">Halted: the escrow wallet is underfunded</p>
            <p className="text-sm">Every money-moving action is disabled until the balance covers open deals. Owner commands and reading still work.</p>
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)_340px]">
        <main className="order-1 space-y-4 lg:order-2 lg:col-start-2 lg:row-start-1">
          <NeedsYou pending={pendingCard} alerts={state.alerts} highlight={state.highlight === "needs"}
            onReview={() => document.getElementById("pending-card")?.scrollIntoView({ behavior: "smooth", block: "center" })} />
          <section aria-label="Conversation" className="space-y-4">
            {turns.length ? turns.map((t, i) => <Turn key={i} turn={t} ctx={ctx} />) : <EmptyChat />}
          </section>
          <Composer disabled={halted} busy={busy} value={draft} setValue={setDraft} onSend={send} onTick={tick} inputRef={inputRef} />
        </main>

        <aside aria-label="Wallet and deals" className="order-2 space-y-4 lg:order-1 lg:col-start-1 lg:row-span-2 lg:row-start-1 xl:row-span-1">
          <Wallet w={state.wallet} />
          <DailyLimit w={state.wallet} />
          {state.suppliers && state.fixture === "reputation" && <Suppliers list={state.suppliers} />}
          <Deals deals={state.deals} />
        </aside>

        <div className="order-3 lg:col-start-2 xl:col-start-3 xl:row-start-1">
          <Feed items={activity} highlight={state.highlight === "feed"} />
        </div>
      </div>
      <footer className="mt-6 text-cap text-ink-2">
        {fixture ? <>Replayed from <span className="font-mono">{state.audit_source}</span> and reports/live transcripts. No model or chain calls.</> : "Live: Sepolia and the configured model."}
      </footer>
    </div>
  );
}
