import { useEffect, useState } from "react";
import { Bot, Clock, Handshake, MessageSquare, Phone, ShieldCheck, Store } from "lucide-react";
import { Shell, go } from "./components/Shell.jsx";
import { Button, Chip, Panel } from "./components/ui.jsx";
import { ConnectChat } from "./Negotiate.jsx";
import { addrUrl, getJSON, query, setExplorer, when } from "./lib.js";

const CHANNEL = { whatsapp: "WhatsApp", telegram: "Telegram", simulator: "WhatsApp simulator" };

/** The owner's supplier directory: saved payees with their on-chain status, and how each one's person is reached. */
export default function Suppliers() {
  const fixture = query();
  const [state, setState] = useState(null);
  const [neg, setNeg] = useState(null);
  const [open, setOpen] = useState(null);
  const [err, setErr] = useState("");
  const load = () => Promise.all([
    getJSON("/api/state", fixture).then((s) => { setExplorer(s.explorer); setState(s); }),
    fixture ? Promise.resolve() : getJSON("/api/negotiations").then(setNeg).catch(() => setNeg(null)),
  ]).catch((e) => setErr(String(e.message || e)));
  useEffect(() => { load(); }, []);

  if (err) return <main className="p-6 text-bad">Could not load suppliers: {err}</main>;
  if (!state) return <main className="p-6 text-ink-2" aria-busy="true">Loading suppliers…</main>;
  const reach = Object.fromEntries((neg?.payees || []).map((p) => [p.address, p]));
  const rep = Object.fromEntries((state.suppliers || []).map((s) => [s.name, s]));

  return (
    <Shell active="suppliers" crumb="Suppliers"
      status={fixture ? "Replayed fixture · no chain calls" : `Live · ${state.network || "Sepolia testnet"}`}>
      <main className="relative min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-9">
        <p className="text-micro tracking-[0.14em] text-ink-2">SUPPLIER DIRECTORY</p>
        <h2 className="mt-2 font-display text-title font-semibold tracking-[-0.02em]">Only these suppliers can be paid</h2>
        <p className="mt-2 max-w-[70ch] text-cap leading-6 text-ink-2">
          To add one, ask in the Agent workspace: “Save a new supplier, Kalinaw Crafts, payout 0x…”. The address must be
          typed by you, it is checked for lookalikes, you confirm with its last 4 characters, and your owner key signs it.
          A new supplier is payable only after the wallet's waiting period.
        </p>
        <div className="mt-6 grid gap-4 xl:grid-cols-2">
          {state.payees?.length ? state.payees.map((p) => {
            const r = reach[p.address] || {}, s = rep[p.name];
            const waiting = p.active_at > state.now;
            return (
              <Panel key={p.address} as="article" title={null} className="bg-raised">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="grid h-9 w-9 place-items-center rounded-lg bg-subtle font-semibold text-accent-text" aria-hidden="true">{p.name[0]}</span>
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-semibold">{p.name}</h3>
                    <a href={addrUrl(p.address)} target="_blank" rel="noreferrer" className="font-mono text-micro text-ink-2">{p.address}</a>
                  </div>
                  {!p.listed ? <Chip tone="bad">Removed</Chip>
                    : waiting ? <Chip tone="warn" icon={Clock}>Payable {when(p.active_at).slice(5)}</Chip>
                    : <Chip tone="ok" icon={ShieldCheck}>Active on-chain</Chip>}
                </div>
                <div className="mt-4 flex flex-wrap gap-1.5">
                  {r.whatsapp ? <Chip tone={r.whatsapp === "simulator" ? "warn" : "ok"} icon={Phone}>{CHANNEL[r.whatsapp] || r.whatsapp}</Chip>
                    : <Chip tone="muted" icon={MessageSquare}>No chat linked</Chip>}
                  {r.agent && <Chip tone="accent" icon={Bot}>Supplier agent</Chip>}
                  {r.api && <Chip tone="ok" icon={Store}>Own system (API)</Chip>}
                  {s && <Chip tone="muted">Record {s.on_time}/{s.late}/{s.non_delivery} · cap {s.cap_pct}%</Chip>}
                </div>
                {!fixture && (
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button variant="ghost" onClick={() => go("negotiate")}><Handshake size={15} aria-hidden="true" />Negotiate</Button>
                    <Button variant="ghost" onClick={() => setOpen(open === p.address ? null : p.address)} aria-expanded={open === p.address}>
                      <MessageSquare size={15} aria-hidden="true" />Connect chat</Button>
                  </div>
                )}
                {open === p.address && neg && (
                  <div className="mt-3 grid grid-cols-2"><ConnectChat p={{ ...p, whatsapp: r.whatsapp }} tg={neg.telegram} onLinked={load} /></div>
                )}
              </Panel>
            );
          }) : <p className="text-sm text-ink-2">No saved suppliers yet.</p>}
        </div>
      </main>
    </Shell>
  );
}
