import { useEffect, useState } from "react";
import { ArrowRight, Ban, Bot, CheckCircle2, Clock, FileWarning, Handshake, KeyRound, Lock, MessageSquare, Phone, Send, ShieldAlert, User, XCircle } from "lucide-react";
import clsx from "clsx";
import { Button, Card, Chip, Panel, Row } from "./components/ui.jsx";
import { day, peso, request, setExplorer, short, txUrl, when } from "./lib.js";
import { logout } from "./Login.jsx";

const P = (units) => peso(units / 100, 2);
const STATE = {
  awaiting_acceptance: ["Waiting for the supplier", "accent"], negotiating: ["Tiwala is answering", "accent"],
  awaiting_clarification: ["Needs a clear reply", "warn"], awaiting_buyer_approval: ["Agreed: your review", "warn"],
  ready_for_escrow: ["Confirm in chat", "warn"], escrow_created: ["Escrow created", "ok"], rejected: ["No deal", "bad"],
  expired: ["Expired", "muted"], cancelled: ["Cancelled", "muted"],
};
const OPEN = new Set(["awaiting_acceptance", "negotiating", "awaiting_clarification"]);
const SOURCE = {
  owner: "you", buyer_rules: "Tiwala (rules)", buyer_model: "Tiwala (model)", supplier_text: "supplier text, read by model",
  supplier_agent_live_model: "supplier agent (live model)", supplier_agent_scripted: "supplier agent (scripted)",
  supplier_console: "supplier's person",
};
const FIELD = { quantity: "Quantity", unit_price: "Unit price", total: "Total", deposit_bps: "Deposit", deliver_by: "Delivery", deposit: "Deposit amount" };
const fmt = (k, v) => (k === "quantity" ? v.toLocaleString("en-US") : k === "deposit_bps" ? `${v / 100}%` : k === "deliver_by" ? day(v) : P(v));

async function call(path, method = "GET", body) {
  const r = await request(path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.detail || `${r.status}`);
  return j;
}

export function ViewNav({ active }) {
  const go = (v) => { const p = new URLSearchParams(); if (v) p.set("view", v); window.location.search = p; };
  return (
    <nav aria-label="Workspace" className="flex gap-1 rounded bg-surface p-1 text-sm">
      {[["", "Payments"], ["negotiate", "Negotiations"]].map(([v, l]) => (
        <button key={l} onClick={() => go(v)} aria-current={active === v ? "page" : undefined}
          className={clsx("min-h-[36px] rounded px-3", active === v ? "bg-raised font-semibold text-ink" : "text-ink-2 hover:text-ink")}>{l}</button>
      ))}
      <button onClick={logout} className="min-h-[36px] rounded px-3 text-ink-2 hover:text-ink">Sign out</button>
    </nav>
  );
}

export function ModeChips({ n }) {
  const sim = n.channel === "simulator";
  return (
    <span className="flex flex-wrap gap-1.5">
      {n.mode === "whatsapp"
        ? <Chip tone={sim ? "warn" : "ok"} icon={Phone} wrap>{sim ? "WhatsApp simulator (local, not WhatsApp)" : "Live WhatsApp"}</Chip>
        : n.mode === "api" ? <Chip tone="ok" icon={Bot} wrap>Supplier's own system (API)</Chip>
        : <Chip tone="accent" icon={Bot} wrap>{n.agent_kind?.startsWith("live_model") ? `Supplier agent: live model ${n.agent_kind.split(":").slice(1).join(":")}` : "Supplier agent: scripted (not AI)"}</Chip>}
      {n.mode === "agent" && <Chip tone={n.controller === "human" ? "warn" : "muted"} icon={n.controller === "human" ? User : Bot}>
        {n.controller === "human" ? "Supplier's person answering" : "Agent answering"}</Chip>}
    </span>
  );
}

function StateChip({ s }) {
  const [label, tone] = STATE[s] || [s, "muted"];
  return <Chip tone={tone}>{label}</Chip>;
}

function OfferCard({ p, diff, product, label }) {
  const t = p.terms;
  return (
    <Card tone={p.by === "buyer" ? "accent" : "warn"} aria-label={label}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Chip tone={p.by === "buyer" ? "accent" : "warn"}>{p.by === "buyer" ? "Your side" : "Supplier"} · v{p.version}</Chip>
        <Chip tone="muted">{p.status}</Chip>{p.final && <Chip tone="warn">Final offer</Chip>}
        <span className="text-cap text-ink-2">from {SOURCE[p.source] || p.source} · code <span className="font-mono">{p.code}</span></span>
      </div>
      <h3 className="mb-3 text-title font-semibold">{t.quantity.toLocaleString("en-US")} × {product} at {P(t.unit_price)}</h3>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        {["total", "deposit_bps", "deliver_by", "unit_price"].map((k) => (
          <div key={k}><dt className="text-ink-2">{FIELD[k]}</dt><dd className="font-mono">{fmt(k, t[k])}{k === "deposit_bps" && <span className="text-ink-2"> ({P(t.deposit)})</span>}</dd></div>
        ))}
      </dl>
      {diff && Object.keys(diff).length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-subtle/60 pt-3 text-sm" aria-label="Changes from the previous offer">
          {Object.entries(diff).filter(([k]) => FIELD[k] && k !== "deposit").map(([k, [a, b]]) => (
            <li key={k} className="flex flex-wrap items-center gap-2"><span className="w-24 text-ink-2">{FIELD[k]}</span>
              <span className="font-mono text-ink-2 line-through">{fmt(k, a)}</span><ArrowRight size={14} aria-hidden="true" /><span className="sr-only">changed to</span>
              <span className="font-mono font-semibold">{fmt(k, b)}</span></li>
          ))}
        </ul>
      )}
      {p.note && <p className="mt-3 text-sm text-ink-2">“{p.note}”</p>}
    </Card>
  );
}

function Conversation({ n }) {
  const status = Object.fromEntries((n.outbox || []).map((o) => [o.ts + o.text.slice(0, 20), o]));
  return (
    <Panel title="Conversation" action={<ModeChips n={n} />}>
      <ol className="max-h-[420px] space-y-2 overflow-y-auto pr-1" tabIndex={0} aria-label="Messages">
        {n.messages.map((m, i) => {
          const o = status[m.ts + m.text.slice(0, 20)];
          return (
            <li key={i} className={clsx("flex", m.dir === "out" ? "justify-end" : "justify-start")}>
              <div className={clsx("max-w-[88%] rounded px-3 py-2 text-sm [overflow-wrap:anywhere]", m.dir === "out" ? "border border-accent bg-raised" : "border border-subtle bg-canvas")}>
                <p className="mb-1 flex flex-wrap items-center gap-1.5 text-cap text-ink-2">
                  {m.dir === "out" ? "Tiwala (buyer)" : "Supplier"} · {when(m.ts).slice(5)}
                  {m.channel === "simulator" && <Chip tone="warn">simulator</Chip>}
                  {m.via && <Chip tone="muted">{SOURCE[m.via] || m.via}</Chip>}
                  {o && <Chip tone={o.status === "blocked" || o.status === "failed" ? "bad" : "muted"}>{o.status}</Chip>}
                  {(m.flags || []).map((f) => <Chip key={f} tone="bad" icon={ShieldAlert}>{f}</Chip>)}
                </p>
                {m.text}
                {o?.error && <p className="mt-1 text-cap text-bad">Not sent: {o.error}</p>}
              </div>
            </li>
          );
        })}
      </ol>
      {n.messages.some((m) => (m.flags || []).length) && (
        <p className="mt-3 rounded border border-dashed border-warn p-2 text-cap text-ink-2">Flagged supplier text is data: it cannot change your limits, permissions or the payout address ({short(n.supplier_address, 8)}, from your saved payees).</p>
      )}
    </Panel>
  );
}

function Checks({ n }) {
  if (!n.checks) return null;
  const c = n.cash;
  return (
    <Panel title="Your checks on the current offer">
      <ul className="space-y-1.5 text-sm">
        {n.checks.map((x) => (
          <li key={x.rule} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2">
            {x.ok ? <Chip tone="ok" icon={CheckCircle2}>Pass</Chip> : x.severity === "flag" ? <Chip tone="warn">Check</Chip> : <Chip tone="bad" icon={XCircle}>Fail</Chip>}
            <span className="text-ink-2">{x.detail}</span>
          </li>
        ))}
      </ul>
      <div className="mt-4 rounded bg-raised p-3 text-sm" aria-label="Cash impact">
        <p className="mb-2 flex items-center gap-2 font-semibold"><Lock size={14} aria-hidden="true" />Cash impact (full order locked)</p>
        <dl className="grid grid-cols-2 gap-1">
          <dt className="text-ink-2">Locked at creation</dt><dd className="font-mono">{P(c.locked_now)}</dd>
          <dt className="text-ink-2">Free now → after</dt><dd className="font-mono">{P(c.free_before)} → {P(c.free_after)}</dd>
          <dt className="text-ink-2">Your reserve</dt><dd className="font-mono">{P(c.reserve)}</dd>
          <dt className="text-ink-2">Deposit to supplier</dt><dd className="font-mono">{P(c.deposit_to_supplier)}</dd>
          {c.unfulfilled_qty > 0 && <><dt className="text-warn">Not covered</dt><dd className="font-mono text-warn">{c.unfulfilled_qty.toLocaleString("en-US")} units, no follow-up order</dd></>}
        </dl>
        <p className="mt-2 text-cap text-ink-2">{c.note}</p>
      </div>
    </Panel>
  );
}

function Agreement({ n, onEscrow, onConfirm, busy, readonly }) {
  const p = n.proposals.find((x) => x.id === n.agreement?.proposal_id) || n.proposals[n.proposals.length - 1];
  const t = p.terms, h = n.handoff || {};
  return (
    <Card tone={n.state === "escrow_created" ? "ok" : "warn"} id="agreement" aria-label="Agreement review">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Chip tone="ok" icon={Handshake}>Both accepted v{p.version}</Chip><StateChip s={n.state} />
      </div>
      <h3 className="mb-1 text-title font-semibold">Agreement with {n.supplier_name}</h3>
      <p className="mb-3 text-sm text-ink-2">Supplier acceptance is not your payment approval. Escrow needs your own yes, after every check runs again on fresh chain data.</p>
      <dl className="divide-y divide-subtle/60">
        <Row label="Terms">{t.quantity.toLocaleString("en-US")} × {n.product} at {P(t.unit_price)} = <strong className="font-mono">{P(t.total)}</strong></Row>
        <Row label="Deposit">{t.deposit_bps / 100}% = <span className="font-mono">{P(t.deposit)}</span>, paid right after the deal is created</Row>
        <Row label="Delivery by">{when(t.deliver_by)}</Row>
        <Row label="Terms hash" mono>{p.terms_hash.slice(0, 24)}… (code {p.code})</Row>
        <Row label="Accepted by">{Object.entries(p.accepted_by).map(([k, a]) => <div key={k}>{k === "buyer" ? "Tiwala within your limits" : `Supplier · ${SOURCE[a.via] || a.via}`} · {when(a.at).slice(5)}</div>)}</Row>
        <Row label="Offer expires">{when(p.expires)}</Row>
        {h.deal_id && <Row label="Escrow">Deal #{h.deal_id}{h.tx && <> · <a href={txUrl(h.tx)} target="_blank" rel="noreferrer" className="font-mono">{short(h.tx, 12)}</a></>}{h.down_tx && <> · deposit <a href={txUrl(h.down_tx)} target="_blank" rel="noreferrer" className="font-mono">{short(h.down_tx, 10)}</a></>}{h.note && <div className="text-cap text-ink-2">{h.note}</div>}</Row>}
      </dl>
      {n.reason && n.state !== "escrow_created" && /Recheck|refused/i.test(n.reason) && <p className="mt-3 text-sm text-bad">{n.reason}</p>}
      {!readonly && n.state === "awaiting_buyer_approval" && (
        <Button className="mt-4" onClick={onEscrow} disabled={busy}><Lock size={16} aria-hidden="true" />Recheck and prepare escrow</Button>
      )}
      {n.pending_card && (
        <div className="mt-4 rounded border border-warn p-3 text-sm">
          <pre className="whitespace-pre-wrap font-sans">{n.pending_card}</pre>
          {!readonly && <Button className="mt-3" onClick={onConfirm} disabled={busy}><CheckCircle2 size={16} aria-hidden="true" />Yes, create the escrow</Button>}
        </div>
      )}
    </Card>
  );
}

function CounterForm({ n, onSubmit, busy }) {
  const t = n.proposals[n.proposals.length - 1].terms;
  const [f, setF] = useState({ quantity: t.quantity, unit_price_php: t.unit_price / 100, deposit_pct: t.deposit_bps / 100, deliver_by: day(t.deliver_by), note: "" });
  const field = (k, label, type = "number") => (
    <label className="text-sm"><span className="mb-1 block text-ink-2">{label}</span>
      <input type={type} value={f[k]} onChange={(e) => setF({ ...f, [k]: type === "number" ? Number(e.target.value) : e.target.value })}
        className="w-full rounded border border-subtle bg-canvas px-2 py-1.5 font-mono text-ink" /></label>
  );
  return (
    <form className="grid grid-cols-2 gap-3 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); onSubmit(f); }} aria-label="Counteroffer">
      {field("quantity", "Quantity")}{field("unit_price_php", "Unit price (₱)")}{field("deposit_pct", "Deposit %")}{field("deliver_by", "Delivery by", "date")}
      <div className="col-span-2 sm:col-span-4"><Button type="submit" disabled={busy}><Send size={16} aria-hidden="true" />Send counteroffer</Button>
        <span className="ml-3 text-cap text-ink-2">Checked against your limits first. A new version cancels any earlier acceptance.</span></div>
    </form>
  );
}

function SimPhone({ n, onSend, busy }) {
  const [text, setText] = useState("");
  return (
    <Panel title="WhatsApp simulator" action={<Chip tone="warn">local, not WhatsApp</Chip>}>
      <p className="mb-2 text-cap text-ink-2">Type as the supplier's person. Same engine and checks as live WhatsApp; nothing leaves this machine.</p>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) { onSend(text); setText(""); } }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={`e.g. ACCEPT ${n.proposals[n.proposals.length - 1]?.code || ""}`}
          className="min-w-0 flex-1 rounded border border-subtle bg-canvas px-3 py-2 text-ink" aria-label="Supplier message" />
        <Button type="submit" disabled={busy || !OPEN.has(n.state)}><MessageSquare size={16} aria-hidden="true" />Send</Button>
      </form>
    </Panel>
  );
}

function NewNegotiation({ payees, onOpen, busy }) {
  const d = (k) => { const x = new Date(Date.now() + k * 86400000); return x.toISOString().slice(0, 10); };
  const [f, setF] = useState({ supplier: payees.find((p) => p.agent)?.name || payees[0]?.name || "", product: "Cotton fabric (metres)", mode: "agent",
    desired_qty: 500, min_qty: 300, target_unit_price_php: 100, max_total_php: 60000, min_reserve_php: 100000,
    preferred_delivery: d(9), latest_delivery: d(20), opening_deposit_pct: 10 });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });
  const inp = (k, label, type = "number") => (
    <label className="text-sm"><span className="mb-1 block text-ink-2">{label}</span>
      <input type={type} value={f[k]} onChange={set(k)} className="w-full rounded border border-subtle bg-canvas px-2 py-1.5 text-ink" /></label>
  );
  const p = payees.find((x) => x.name === f.supplier);
  return (
    <Panel title="New negotiation">
      <form className="grid grid-cols-2 gap-3" onSubmit={(e) => { e.preventDefault(); onOpen(f); }}>
        <label className="col-span-2 text-sm"><span className="mb-1 block text-ink-2">Supplier (saved payees only)</span>
          <select value={f.supplier} onChange={set("supplier")} className="w-full rounded border border-subtle bg-canvas px-2 py-1.5 text-ink">
            {payees.map((x) => <option key={x.address}>{x.name}</option>)}</select></label>
        <label className="col-span-2 text-sm"><span className="mb-1 block text-ink-2">Who answers for the supplier</span>
          <select value={f.mode} onChange={set("mode")} className="w-full rounded border border-subtle bg-canvas px-2 py-1.5 text-ink">
            <option value="agent" disabled={!p?.agent}>Supplier agent, simulated on this server{p?.agent ? "" : " (not set up)"}</option>
            <option value="whatsapp" disabled={!p?.whatsapp}>Supplier's person on WhatsApp{p?.whatsapp ? ` (${p.whatsapp})` : " (no opted-in contact)"}</option>
            <option value="api" disabled={!p?.api}>Supplier's own system (API){p?.api ? "" : " (not connected)"}</option></select></label>
        <div className="col-span-2">{inp("product", "Product", "text")}</div>
        {inp("desired_qty", "Quantity wanted")}{inp("min_qty", "Minimum quantity")}
        {inp("target_unit_price_php", "Opening unit price (₱)")}{inp("max_total_php", "Most you will commit (₱)")}
        {inp("min_reserve_php", "Cash to keep free (₱)")}{inp("opening_deposit_pct", "Opening deposit %")}
        {inp("preferred_delivery", "Preferred delivery", "date")}{inp("latest_delivery", "Latest delivery", "date")}
        <p className="col-span-2 text-cap text-ink-2">These limits stay on your side: the supplier and their agent never see them. The deposit ceiling comes from the supplier's reputation and the contract.</p>
        <div className="col-span-2"><Button type="submit" disabled={busy || !f.supplier}><Handshake size={16} aria-hidden="true" />Start negotiating</Button></div>
      </form>
    </Panel>
  );
}

export default function Negotiate() {
  const fixture = new URLSearchParams(window.location.search).get("fixture");
  const [data, setData] = useState(null);
  const [sel, setSel] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const load = async () => {
    try {
      const j = await call(`/api/negotiations${fixture ? `?fixture=${fixture}` : ""}`);
      setExplorer(j.explorer); setData(j);
      setSel((s) => s || j.negotiations[0]?.id || null);
    } catch (e) { setErr(String(e.message || e)); }
  };
  useEffect(() => { load(); }, []);
  const n = data?.negotiations.find((x) => x.id === sel);
  useEffect(() => {
    if (fixture || !n || !(n.running || ["negotiating", "ready_for_escrow"].includes(n.state))) return undefined;
    const id = setInterval(load, 1500);
    return () => clearInterval(id);
  }, [n?.running, n?.state, n?.proposals.length]);

  const act = async (fn) => { setBusy(true); setErr(""); try { await fn(); await load(); } catch (e) { setErr(String(e.message || e)); } finally { setBusy(false); } };
  const open = (f) => act(async () => { const r = await call("/api/negotiations", "POST", f); setSel(r.id); });
  const counter = (f) => act(() => call(`/api/negotiations/${n.id}/counter`, "POST", f));
  const close = (what) => act(() => call(`/api/negotiations/${n.id}/${what}`, "POST"));
  const escrow = () => act(() => call(`/api/negotiations/${n.id}/escrow`, "POST"));
  const confirm = () => act(() => call("/api/confirm", "POST", {}));
  const simSend = (text) => act(() => call("/api/sim/whatsapp/inbound", "POST", { supplier: n.supplier_address, text }));

  if (err && !data) return <main className="p-6 text-bad">Could not load negotiations: {err}</main>;
  if (!data) return <main className="p-6 text-ink-2" aria-busy="true">Loading negotiations…</main>;
  const props = n?.proposals || [];
  const cur = props[props.length - 1];
  const agreed = n && ["awaiting_buyer_approval", "ready_for_escrow", "escrow_created"].includes(n.state);

  return (
    <div className="mx-auto max-w-[1440px] px-4 py-4 lg:px-6">
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-section font-bold tracking-tight">Tiwala</h1>
          <p className="text-sm text-ink-2">Negotiate supplier terms, then lock the exact agreement in escrow · {data?.network || "Sepolia testnet"}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {fixture && <Chip tone="accent" icon={FileWarning} wrap>Replayed: {data.fixture?.title}</Chip>}
          {fixture && data.fixture?.validation && <Chip tone="muted" wrap>{data.fixture.validation}</Chip>}
          {!fixture && data.whatsapp && <Chip tone={data.whatsapp.receive || data.whatsapp.send ? "ok" : "muted"} icon={Phone} wrap>{data.whatsapp.receive ? "WhatsApp webhook configured" : data.whatsapp.send ? "WhatsApp: live sending, replies via simulator" : "WhatsApp: simulator only (no credentials)"}</Chip>}
          <ViewNav active="negotiate" />
        </div>
      </header>
      {err && <p role="alert" className="mb-4 rounded border border-bad bg-raised p-3 text-sm text-bad">{err}</p>}
      {!fixture && data.whatsapp?.missing?.length > 0 && (
        <details className="mb-4 rounded border border-subtle bg-surface p-3 text-sm">
          <summary className="cursor-pointer text-ink-2">Why live WhatsApp cannot send yet ({data.whatsapp.missing.length})</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-2">
            {data.whatsapp.missing.map((x) => <li key={x}>{x}</li>)}
            <li>Each supplier also needs an opted-in WhatsApp contact; only local simulator contacts exist now.</li>
          </ul>
        </details>
      )}
      <div className="grid gap-4 lg:grid-cols-[320px_minmax(0,1fr)] xl:grid-cols-[320px_minmax(0,1fr)_360px]">
        <aside className="space-y-4" aria-label="Negotiations">
          {!fixture && data.payees && <NewNegotiation payees={data.payees} onOpen={open} busy={busy} />}
          <Panel title="Negotiations">
            {data.negotiations.length ? <ul className="space-y-1.5">{data.negotiations.map((x) => (
              <li key={x.id}><button onClick={() => setSel(x.id)} aria-current={x.id === sel ? "true" : undefined}
                className={clsx("w-full rounded p-2 text-left text-sm", x.id === sel ? "bg-raised" : "hover:bg-raised/60")}>
                <span className="flex flex-wrap items-center justify-between gap-1"><span className="font-semibold">{x.supplier_name}</span><StateChip s={x.state} /></span>
                <span className="text-cap text-ink-2">{x.product} · {x.proposals.length} offers · <span className="font-mono">NEG-{x.id}</span></span>
              </button></li>))}</ul> : <p className="text-sm text-ink-2">No negotiations yet.</p>}
          </Panel>
        </aside>

        {n ? (
          <main className="min-w-0 space-y-4" aria-label="Negotiation">
            <section className="rounded bg-surface p-4" aria-label="Status">
              <div className="flex flex-wrap items-center gap-2"><h2 className="text-title font-semibold">{n.product} · {n.supplier_name}</h2><StateChip s={n.state} />
                {n.running && <Chip tone="accent" icon={Clock}>Agents exchanging offers…</Chip>}{n.escalated && <Chip tone="warn" icon={User}>Needs a person</Chip>}</div>
              <p className="mt-1 text-sm text-ink-2">{n.reason || "Offers go back and forth within both sides' limits."} · round {props.length} of {n.max_rounds}</p>
            </section>
            {agreed ? <Agreement n={n} onEscrow={escrow} onConfirm={confirm} busy={busy} readonly={!!fixture} />
              : cur && <OfferCard p={cur} diff={n.diff} product={n.product} label="Current offer" />}
            <Conversation n={n} />
            {!fixture && OPEN.has(n.state) && (
              <Panel title="Your controls">
                <CounterForm key={cur?.id} n={n} onSubmit={counter} busy={busy} />
                <div className="mt-4 flex flex-wrap gap-3 border-t border-subtle/60 pt-4">
                  <Button variant="ghost" onClick={() => close("reject")} disabled={busy}><XCircle size={16} aria-hidden="true" />Reject offer</Button>
                  <Button variant="ghost" onClick={() => close("cancel")} disabled={busy}><Ban size={16} aria-hidden="true" />Cancel negotiation</Button>
                </div>
              </Panel>
            )}
          </main>
        ) : <main className="text-sm text-ink-2">Start a negotiation to see it here.</main>}

        {n && (
          <aside className="min-w-0 space-y-4 lg:col-start-2 xl:col-start-3" aria-label="Checks and timeline">
            {n.mode === "whatsapp" && n.channel === "simulator" && !fixture && <SimPhone n={n} onSend={simSend} busy={busy} />}
            <Checks n={n} />
            <Panel title="Timeline">
              <ol className="space-y-1 text-sm">{n.timeline.slice(-12).map((e, i) => (
                <li key={i} className="grid grid-cols-[88px_minmax(0,1fr)] gap-2"><span className="font-mono text-cap text-ink-2">{when(e.ts).slice(5)}</span><span>{STATE[e.detail]?.[0] || e.detail || e.event}</span></li>))}</ol>
            </Panel>
          </aside>
        )}
      </div>
      <footer className="mt-6 text-cap text-ink-2">{fixture ? "Replayed from reports/negotiation. No model, WhatsApp or chain calls." : "Negotiation never moves money: escrow needs your own yes through the payment checks."}</footer>
    </div>
  );
}
