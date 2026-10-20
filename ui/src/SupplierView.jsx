import { useEffect, useState } from "react";
import { Bot, CheckCircle2, FileWarning, Hand, Play, Save, Send, User, XCircle } from "lucide-react";
import { Button, Card, Chip, Panel } from "./components/ui.jsx";
import { day, peso, request, when } from "./lib.js";
import { ModeChips } from "./Negotiate.jsx";
import { Shell } from "./components/Shell.jsx";

const P = (u) => peso(u / 100, 2);

/** The supplier's own console: their mandate and their side of each negotiation. No buyer limits are ever sent here. */
export default function SupplierView() {
  const q = new URLSearchParams(window.location.search);
  const supplier = q.get("supplier") || "", fixture = q.get("fixture");
  // The token rides in the #fragment (never sent to the server or in Referer) and goes out only as a header.
  const [token] = useState(() => {
    const t = new URLSearchParams(window.location.hash.slice(1)).get("token") || q.get("token") || "";
    if (t) { q.delete("token"); window.history.replaceState(null, "", `?${q}`); }
    try { if (t) sessionStorage.setItem(`tiwala-supplier-${supplier}`, t); return t || sessionStorage.getItem(`tiwala-supplier-${supplier}`) || ""; }
    catch { return t; }
  });
  const auth = { "X-Supplier-Token": token };
  const base = fixture ? `?fixture=${fixture}` : `?supplier=${encodeURIComponent(supplier)}`;
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => request(`/api/supplier${base}`, { headers: auth }).then(async (r) => { const j = await r.json(); if (!r.ok) throw new Error(j.detail); setD(j); }).catch((e) => setErr(String(e.message)));
  useEffect(() => { load(); const id = fixture ? null : setInterval(load, 2000); return () => id && clearInterval(id); }, []);
  const post = async (path, body, method = "POST") => {
    setBusy(true); setErr("");
    try {
      const r = await request(path + (path.includes("?") ? "&" : "?") + `supplier=${encodeURIComponent(supplier)}`, { method, headers: { "Content-Type": "application/json", ...auth }, body: body ? JSON.stringify(body) : undefined });
      const j = await r.json(); if (!r.ok) throw new Error(j.detail); await load();
    } catch (e) { setErr(String(e.message)); } finally { setBusy(false); }
  };
  if (err && !d) return <main className="p-6 text-bad">Supplier console: {err}</main>;
  if (!d) return <main className="p-6 text-ink-2">Loading…</main>;
  return (
    <Shell owner={false} crumb="Supplier console" status={fixture ? "Replayed fixture · no model or chain calls" : `Signed in as ${d.name} with your supplier link`}
      actions={fixture ? <Chip tone="accent" icon={FileWarning}>Replayed fixture</Chip> : null}>
      <main className="relative min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-9">
        <p className="text-micro tracking-[0.14em] text-ink-2">YOUR SIDE OF THE DEAL</p>
        <h2 className="mt-2 font-display text-title font-semibold tracking-[-0.02em]">Supplier console · {d.name}</h2>
        <p className="mt-2 max-w-[70ch] text-cap leading-6 text-ink-2">Your limits and your agent. The buyer never sees this page, and the buyer's limits are never sent to it.
          Accept an offer here or reply <span className="font-mono text-ink">ACCEPT &lt;code&gt;</span> in chat; only the exact open offer can be accepted.</p>
        {err && <p role="alert" className="mt-4 rounded-md border border-bad/60 bg-raised p-3 text-sm text-bad">{err}</p>}
        <div className="mt-6 grid gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
          <Mandate m={d.mandate} readonly={!!fixture} busy={busy} onSave={(f) => post("/api/supplier/mandate", f, "PUT")} />
          <div className="min-w-0 space-y-4">
            {d.negotiations.map((n) => <SupplierNeg key={n.id} n={n} readonly={!!fixture} busy={busy}
              act={(what, move) => post(`/api/supplier/negotiations/${n.id}/${what}`, move)} />)}
            {!d.negotiations.length && <p className="text-sm text-ink-2">No negotiations yet.</p>}
          </div>
        </div>
      </main>
    </Shell>
  );
}

function Mandate({ m, onSave, busy, readonly }) {
  const [f, setF] = useState(m ? { list_unit_price_php: m.list_unit_price / 100, min_unit_price_php: m.min_unit_price / 100, available_qty: m.available_qty,
    min_order_qty: m.min_order_qty, earliest_delivery: day(m.earliest_delivery), min_deposit_pct: m.min_deposit_bps / 100,
    deposit_tiers: m.deposit_tiers.map(([qq, b]) => [qq, b / 100]), agent_may_accept: m.agent_may_accept } : { list_unit_price_php: 150, min_unit_price_php: 110,
    available_qty: 450, min_order_qty: 200, earliest_delivery: new Date(Date.now() + 6 * 864e5).toISOString().slice(0, 10), min_deposit_pct: 15, deposit_tiers: [[400, 20]], agent_may_accept: true });
  const inp = (k, label, type = "number") => (
    <label className="text-sm"><span className="mb-1 block text-ink-2">{label}</span>
      <input type={type} value={f[k]} disabled={readonly} onChange={(e) => setF({ ...f, [k]: type === "number" ? Number(e.target.value) : e.target.value })}
        className="w-full rounded-md border border-subtle bg-canvas px-2 py-1.5 text-ink" /></label>
  );
  return (
    <Panel title="Your agent's mandate" action={<Chip tone="muted">private to you</Chip>}>
      <form className="grid grid-cols-2 gap-3" onSubmit={(e) => { e.preventDefault(); onSave(f); }}>
        {inp("list_unit_price_php", "Opening price (₱)")}{inp("min_unit_price_php", "Lowest price (₱)")}
        {inp("available_qty", "Units in stock")}{inp("min_order_qty", "Minimum order")}
        {inp("earliest_delivery", "Earliest delivery", "date")}{inp("min_deposit_pct", "Minimum deposit %")}
        <p className="col-span-2 text-cap text-ink-2">Larger orders: {f.deposit_tiers.map(([qq, b]) => `${qq}+ units need ${b}%`).join(", ") || "none"}.</p>
        <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={f.agent_may_accept} disabled={readonly}
          onChange={(e) => setF({ ...f, agent_may_accept: e.target.checked })} />Agent may accept offers inside these limits</label>
        {!readonly && <div className="col-span-2"><Button type="submit" disabled={busy}><Save size={16} aria-hidden="true" />Save mandate</Button></div>}
      </form>
    </Panel>
  );
}

function SupplierNeg({ n, act, busy, readonly }) {
  const cur = n.proposals[n.proposals.length - 1];
  const t = cur?.terms;
  const [c, setC] = useState(t ? { quantity: t.quantity, unit_price_php: t.unit_price / 100, deposit_pct: t.deposit_bps / 100, deliver_by: day(t.deliver_by), note: "" } : null);
  const human = n.controller === "human";
  const open = cur && cur.by === "buyer" && cur.status === "open" && ["awaiting_acceptance", "awaiting_clarification"].includes(n.state);
  return (
    <Card tone="accent" aria-label={`Negotiation ${n.id}`}>
      <div className="mb-2 flex flex-wrap items-center gap-2"><h2 className="text-title font-semibold">{n.product}</h2><ModeChips n={n} /><Chip tone="muted">{n.state.replaceAll("_", " ")}</Chip></div>
      {t && <p className="text-sm">Buyer offer v{cur.version}: <span className="font-mono">{t.quantity} × {P(t.unit_price)} = {P(t.total)}</span>, {t.deposit_bps / 100}% deposit, delivery by {day(t.deliver_by)} <span className="text-ink-2">(code {cur.code}, expires {when(cur.expires).slice(5)})</span></p>}
      {!readonly && n.mode === "agent" && (
        <div className="mt-3 flex flex-wrap gap-2">
          {human ? <Button variant="ghost" onClick={() => act("handback")} disabled={busy}><Play size={16} aria-hidden="true" />Hand back to my agent</Button>
            : <Button variant="ghost" onClick={() => act("takeover")} disabled={busy}><Hand size={16} aria-hidden="true" />Pause agent and take over</Button>}
          <span className="self-center text-cap text-ink-2">{human ? <><User size={12} className="inline" /> You are answering; your agent's pending moves are discarded.</> : <><Bot size={12} className="inline" /> Your agent is answering within your mandate.</>}</span>
        </div>
      )}
      {!readonly && human && open && c && (
        <div className="mt-4 space-y-3 border-t border-subtle/60 pt-4">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => act("move", { type: "accept", base_version: cur.version, proposal_id: cur.id, terms_hash: cur.terms_hash })} disabled={busy}><CheckCircle2 size={16} aria-hidden="true" />Accept v{cur.version}</Button>
            <Button variant="ghost" onClick={() => act("move", { type: "reject", base_version: cur.version, reason: "Not possible for us." })} disabled={busy}><XCircle size={16} aria-hidden="true" />Reject</Button>
          </div>
          <form className="grid grid-cols-2 gap-2 sm:grid-cols-4" onSubmit={(e) => { e.preventDefault(); act("move", { type: "counter", base_version: cur.version, terms: c }); }}>
            {[["quantity", "Qty"], ["unit_price_php", "Price ₱"], ["deposit_pct", "Deposit %"], ["deliver_by", "Delivery"]].map(([k, l]) => (
              <label key={k} className="text-sm"><span className="mb-1 block text-ink-2">{l}</span>
                <input type={k === "deliver_by" ? "date" : "number"} value={c[k]} onChange={(e) => setC({ ...c, [k]: k === "deliver_by" ? e.target.value : Number(e.target.value) })}
                  className="w-full rounded border border-subtle bg-canvas px-2 py-1.5 font-mono text-ink" /></label>))}
            <div className="col-span-2 sm:col-span-4"><Button type="submit" disabled={busy}><Send size={16} aria-hidden="true" />Counteroffer</Button></div>
          </form>
        </div>
      )}
      <ol className="relative mt-4 max-h-64 space-y-1 overflow-y-auto text-sm" tabIndex={0} aria-label="Messages">
        {n.messages.map((m, i) => <li key={i} className="text-ink-2"><span className="font-mono text-cap">{when(m.ts).slice(11)}</span> {m.dir === "out" ? "Buyer" : "You"}: <span className="text-ink">{m.text}</span></li>)}
      </ol>
    </Card>
  );
}
