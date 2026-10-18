import { Lock, ShieldAlert, ShieldCheck, TrendingDown } from "lucide-react";
import { Chip, Panel } from "./ui.jsx";
import { day, peso, when } from "../lib.js";

const STAGE_TONE = { Locked: "accent", "DP paid": "warn", Delivered: "accent", Completed: "ok", Refunded: "muted", Disputed: "bad" };

export function Wallet({ w }) {
  const total = Math.max(w.free + w.locked, 1);
  return (
    <Panel title="Escrow wallet">
      <p className="font-mono text-section font-semibold">{peso(w.underfunded ? w.balance : w.free + w.locked)}</p>
      <div className="my-3 flex h-2 overflow-hidden rounded-full bg-canvas" aria-hidden="true">
        <div className="bg-accent" style={{ width: `${(w.free * 100) / total}%` }} />
        <div className="bg-ink" style={{ width: `${(w.locked * 100) / total}%` }} />
      </div>
      <dl className="grid grid-cols-2 gap-2 text-sm">
        <div><dt className="text-ink-2">Free</dt><dd className="font-mono">{peso(w.free)}</dd></div>
        <div><dt className="flex items-center gap-1 text-ink-2"><Lock size={12} aria-hidden="true" />Locked in deals</dt><dd className="font-mono">{peso(w.locked)}</dd></div>
      </dl>
      {w.underfunded && <p className="mt-2"><Chip tone="bad" icon={ShieldAlert}>Underfunded</Chip></p>}
      <p className="mt-3 text-cap text-ink-2">Snapshot: {w.source}</p>
    </Panel>
  );
}

export function Accounts({ accounts, links, highlight }) {
  return (
    <Panel title="Linked accounts" highlight={highlight} action={<Chip tone="ok" icon={ShieldCheck}>Read-only</Chip>}>
      <ul className="space-y-1 text-sm">
        {accounts.map((a) => (
          <li key={a.provider} className="flex justify-between"><span>{a.provider}</span><span className="font-mono">{peso(a.balance_php)}</span></li>
        ))}
      </ul>
      {links.map((l) => (
        <div key={l.id} className="mt-3 rounded border border-ok p-3 text-sm" aria-label="Consent record">
          <p className="mb-1 flex flex-wrap items-center gap-2 font-semibold">Account linked <Chip tone="ok">Consent recorded</Chip></p>
          <dl className="space-y-0.5 text-ink-2">
            <div><dt className="inline">Provider: </dt><dd className="inline text-ink">{l.label} ({l.provider})</dd></div>
            <div><dt className="inline">Scope: </dt><dd className="inline text-ink">{l.consent.scope}</dd></div>
            <div><dt className="inline">Consent given: </dt><dd className="inline font-mono text-ink">{when(l.consent.given_at)}</dd></div>
            <div><dt className="inline">Link id: </dt><dd className="inline font-mono text-ink">{l.id}</dd></div>
          </dl>
          <p className="mt-1 text-cap text-ink-2">RA 10173: balances only, no secrets in the log (audit line {l.line}). Unlink any time.</p>
        </div>
      ))}
    </Panel>
  );
}

export function DailyLimit({ w }) {
  const pct = Math.round((w.daily_left * 100) / w.daily_cap);
  return (
    <Panel title="Agent daily limit">
      <p className="text-base"><span className="font-mono font-semibold">{peso(w.daily_left)}</span> <span className="text-ink-2">left of {peso(w.daily_cap)}</span></p>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-canvas" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Daily limit left">
        <div className="h-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2 text-cap text-ink-2">Per deal up to {peso(w.per_deal_cap)}. Enforced by the contract, not the model.{w.paused ? " Paused." : ""}</p>
    </Panel>
  );
}

export function Suppliers({ list }) {
  return (
    <Panel title="Supplier reputation" highlight>
      <table className="w-full text-left text-sm">
        <thead><tr className="text-cap text-ink-2"><th className="pb-1 font-medium">Supplier</th><th className="font-medium">Record</th><th className="font-medium">R</th><th className="font-medium">Cap</th></tr></thead>
        <tbody>
          {list.map((s) => (
            <tr key={s.name} className="border-t border-subtle/60 align-top">
              <td className="py-1.5">{s.name}</td>
              <td className="font-mono">{s.on_time}/{s.late}/
                <span className={s.was && s.was.non_delivery !== s.non_delivery ? "font-semibold text-bad" : ""}>{s.non_delivery}</span>
                {s.was && s.was.non_delivery !== s.non_delivery && (
                  <div className="font-sans text-cap text-bad"><TrendingDown size={12} className="inline" aria-hidden="true" /> non-delivery {s.was.non_delivery} → {s.non_delivery}</div>
                )}
              </td>
              <td className="font-mono">{s.r.toFixed(2)}</td>
              <td className="font-mono">{s.cap_pct}%{s.was && <div className="font-sans text-cap text-ink-2">{s.was.cap_pct === s.cap_pct ? "unchanged, at the floor" : `was ${s.was.cap_pct}%`}</div>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-cap text-ink-2">Record: on time / late / non-delivery, from closed deals on-chain across all buyers.</p>
    </Panel>
  );
}

export function Deals({ deals }) {
  return (
    <Panel title="Deals">
      <ul className="divide-y divide-subtle/60">
        {[...deals].reverse().map((d) => (
          <li key={d.id} className="py-2 text-sm">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold">#{d.id} · {d.supplier}</span>
              <Chip tone={STAGE_TONE[d.stage]}>{d.stage}</Chip>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-ink-2">
              <span className="font-mono">{peso(d.total_php)}</span><span>· {d.down_pct}% down</span><span>· by {day(d.deadline)}</span>
            </div>
            <div className="mt-0.5 truncate font-mono text-cap text-ink-2" title={d.ref}>
              {d.ref_flags.length ? <><Chip tone="bad" className="mr-1 font-sans">Untrusted note</Chip>{d.ref.split(" ")[0]}…</> : d.ref}
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
