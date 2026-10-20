import { useState } from "react";
import clsx from "clsx";
import { Bot, CheckCircle2, Clock, PanelRight, ShieldAlert, ShieldCheck, TrendingDown, Wallet as WalletIcon } from "lucide-react";
import { Chip } from "./ui.jsx";
import { FeedList } from "./Feed.jsx";
import { addrUrl, day, peso, when } from "../lib.js";

const STAGE_TONE = { Locked: "accent", "DP paid": "warn", Delivered: "accent", Completed: "ok", Refunded: "muted", Disputed: "bad" };
const OPEN_STAGES = new Set(["Locked", "DP paid", "Delivered", "Disputed"]);
export const openDeals = (deals = []) => deals.filter((d) => OPEN_STAGES.has(d.stage));

export function Wallet({ w, network }) {
  const total = Math.max(w.free + w.locked, 1);
  return (
    <section aria-label="Escrow wallet">
      <div className="flex items-center gap-3 text-sm">
        <span className="grid h-9 w-9 place-items-center rounded-lg border border-subtle bg-accent-soft text-accent-text"><WalletIcon size={17} aria-hidden="true" /></span>
        <div>Escrow wallet<span className="block text-micro text-ink-2">{w.source}</span></div>
        <span className="ml-auto rounded border border-subtle px-1.5 py-1 text-micro tracking-widest text-ink-2">{network?.startsWith("Sepolia") ? "SEPOLIA" : "LOCAL"}</span>
      </div>
      <p className="mt-6 font-display text-[34px] font-medium tracking-[-0.04em]">{peso(w.underfunded ? w.balance : w.free + w.locked)}</p>
      <p className="mt-1 text-micro text-ink-2">Total in escrow wallet · tPHP</p>
      <div className="mt-5 h-1.5 overflow-hidden rounded-full bg-subtle" aria-hidden="true">
        <div className="h-full rounded-full bg-accent" style={{ width: `${(w.free * 100) / total}%` }} />
      </div>
      <dl className="mt-4 grid grid-cols-2 gap-4">
        <div><dt className="flex items-center gap-2 text-micro text-ink-2"><span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />Available</dt>
          <dd className="mt-1.5 font-display text-[18px] font-medium">{peso(w.free)}</dd></div>
        <div><dt className="flex items-center gap-2 text-micro text-ink-2"><span className="h-1.5 w-1.5 rounded-full bg-[#7d8c6d]" aria-hidden="true" />Locked in escrow</dt>
          <dd className="mt-1.5 font-display text-[18px] font-medium">{peso(w.locked)}</dd></div>
      </dl>
      {w.underfunded && <p className="mt-3"><Chip tone="bad" icon={ShieldAlert}>Underfunded</Chip></p>}
    </section>
  );
}

export function DailyLimit({ w }) {
  const pct = w.daily_cap ? Math.round((w.daily_left * 100) / w.daily_cap) : 0;
  return (
    <section aria-label="Agent limits" className="mt-6">
      <p className="flex justify-between gap-3 text-micro text-ink-2"><span>Agent daily limit remaining</span>
        <strong className="font-normal text-ink">{peso(w.daily_left)} <span className="text-ink-2">/ {peso(w.daily_cap)}</span></strong></p>
      <div className="mt-2.5 h-[3px] rounded-full bg-subtle" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Daily limit left">
        <div className="h-full rounded-full bg-[#8fa874]" style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-2.5 text-micro text-ink-2">
        Per deal up to {peso(w.per_deal_cap)}{w.approval_threshold != null && <>; acts alone up to {peso(w.approval_threshold)}</>}. Enforced by the contract.{w.paused ? " Paused." : ""}
      </p>
    </section>
  );
}

export function Payees({ list, now, highlight }) {
  if (!list?.length) return <p className="py-6 text-sm text-ink-2">No saved payees yet. Ask TR8DE to save one.</p>;
  return (
    <ul className={clsx("divide-y divide-line", highlight && "ring-2 ring-warn")} aria-label="Saved payees">
      {list.map((p) => {
        const waiting = p.active_at > now;
        return (
          <li key={p.address} className="flex flex-wrap items-center gap-3 py-3">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-subtle text-cap font-semibold text-accent-text" aria-hidden="true">{p.name[0]}</span>
            <span className="min-w-0 flex-1 text-sm">{p.name}
              <a href={addrUrl(p.address)} target="_blank" rel="noreferrer" className="block font-mono text-micro text-ink-2">{p.address.slice(0, 6)}…{p.address.slice(-4)}</a></span>
            {!p.listed ? <Chip tone="bad">Removed</Chip>
              : waiting ? <Chip tone="warn" icon={Clock}>Payable {when(p.active_at).slice(5)}</Chip>
              : <Chip tone="ok">Active</Chip>}
          </li>
        );
      })}
    </ul>
  );
}

export function Suppliers({ list }) {
  return (
    <section aria-label="Supplier reputation" className="mt-4">
      <table className="w-full text-left text-sm">
        <thead><tr className="text-micro text-ink-2"><th className="pb-1 font-medium">Supplier</th><th className="font-medium">Record</th><th className="font-medium">R</th><th className="font-medium">Cap</th></tr></thead>
        <tbody>
          {list.map((s) => (
            <tr key={s.name} className="border-t border-line align-top">
              <td className="py-2">{s.name}</td>
              <td className="font-mono">{s.on_time}/{s.late}/
                <span className={s.was && s.was.non_delivery !== s.non_delivery ? "font-semibold text-bad" : ""}>{s.non_delivery}</span>
                {s.was && s.was.non_delivery !== s.non_delivery && (
                  <div className="font-sans text-micro text-bad"><TrendingDown size={12} className="inline" aria-hidden="true" /> non-delivery {s.was.non_delivery} → {s.non_delivery}</div>
                )}
              </td>
              <td className="font-mono">{s.r.toFixed(2)}</td>
              <td className="font-mono">{s.cap_pct}%{s.was && <div className="font-sans text-micro text-ink-2">{s.was.cap_pct === s.cap_pct ? "unchanged, at the floor" : `was ${s.was.cap_pct}%`}</div>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-micro text-ink-2">Record: on time / late / non-delivery, from closed deals on-chain across all buyers.</p>
    </section>
  );
}

export function Deals({ deals }) {
  if (!deals.length) return <p className="py-6 text-sm text-ink-2">No escrow deals yet.</p>;
  return (
    <ul className="divide-y divide-line" aria-label="Escrow deals">
      {[...deals].reverse().map((d) => (
        <li key={d.id} className="py-4">
          <div className="flex items-center justify-between gap-2 text-sm">
            <strong className="font-medium">#{d.id} · {d.supplier}</strong><span className="font-display">{peso(d.total_php)}</span>
          </div>
          <p className="mt-1 text-cap text-ink-2">{d.down_pct}% down · deliver by {day(d.deadline)}</p>
          <div className="mt-2 flex min-w-0 items-center gap-2">
            <Chip tone={STAGE_TONE[d.stage]}>{d.stage}</Chip>
            <span className="truncate font-mono text-micro text-ink-2" title={d.ref}>
              {d.ref_flags.length ? <><Chip tone="bad" className="mr-1 font-sans">Untrusted note</Chip>{d.ref.split(" ")[0]}…</> : d.ref}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

const ROLES = [
  ["coordinator", "Coordinator", "Turns your words into a drafted action", Bot],
  ["treasury", "Treasury", "Checks cash and forecasts commitments", WalletIcon],
  ["checker", "Checker", "Independently reviews every payment", CheckCircle2],
];

function Team({ agents }) {
  return (
    <section aria-label="Your agent team" className="mt-6">
      <div className="mb-2 flex items-center justify-between"><h3 className="text-sm font-medium">Your agent team</h3><span className="text-micro text-ink-2">3 roles, one workflow</span></div>
      <ul>
        {ROLES.map(([k, name, what, Icon]) => {
          const m = agents?.[k];
          const off = m === "off";
          return (
            <li key={k} className="flex items-center gap-3 border-b border-line py-3">
              <span className="grid h-7 w-7 place-items-center rounded-md border border-subtle bg-accent-soft text-accent-text" aria-hidden="true"><Icon size={14} /></span>
              <div className="min-w-0 text-cap">{name}<span className="block text-micro text-ink-2">{what}</span></div>
              <span className={clsx("ml-auto flex max-w-[45%] items-center gap-1.5 truncate text-micro", off ? "text-warn" : "text-ok")} title={m || ""}>
                <span className={clsx("h-1 w-1 shrink-0 rounded-full", off ? "bg-warn" : "bg-ok")} aria-hidden="true" />{m ? (off ? "Off: no model key" : m) : "Ready"}
              </span>
            </li>
          );
        })}
      </ul>
      <div className="mt-6 flex gap-3 rounded-md border border-subtle bg-raised p-4">
        <ShieldCheck size={16} className="shrink-0 text-accent-text" aria-hidden="true" />
        <div><p className="text-cap font-medium text-accent-text">Designed to keep you in control</p>
          <p className="mt-1 text-micro leading-5 text-ink-2">Agents propose. Code checks your words and the policy. You approve when required. The contract enforces every limit.</p></div>
      </div>
    </section>
  );
}

const TABS = [["activity", "Activity"], ["deals", "Escrows"], ["payees", "Payees"]];

/** Right-hand canvas of the design: wallet, limits, activity / escrows / payees, and the agent team. */
export function Treasury({ state, activity, initialTab = "activity", highlightFeed }) {
  const [tab, setTab] = useState(initialTab);
  return (
    <div>
      <div className="flex h-14 items-center justify-between border-b border-line px-6 text-cap text-ink-2">
        <span className="flex items-center gap-2"><PanelRight size={15} aria-hidden="true" />Treasury overview</span>
        <span className="text-micro">{state.network || "Sepolia testnet"}</span>
      </div>
      <div className="px-6 pb-5 pt-6">
        <Wallet w={state.wallet} network={state.network || "Sepolia testnet"} />
        <DailyLimit w={state.wallet} />
        <div role="tablist" aria-label="Treasury sections" className="mt-6 flex gap-6 border-b border-line">
          {TABS.map(([k, label]) => (
            <button key={k} role="tab" id={`tab-${k}`} aria-selected={tab === k} aria-controls={`panel-${k}`} onClick={() => setTab(k)}
              className={clsx("border-b-2 pb-3 pt-3 text-cap", tab === k ? "border-accent text-ink" : "border-transparent text-ink-2 hover:text-ink")}>
              {label}{k === "deals" && openDeals(state.deals).length ? ` (${openDeals(state.deals).length})` : ""}
            </button>
          ))}
        </div>
        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="min-h-[200px]">
          {tab === "activity" && <FeedList items={activity} highlight={highlightFeed} />}
          {tab === "deals" && <Deals deals={state.deals} />}
          {tab === "payees" && <><Payees list={state.payees} now={state.now} highlight={state.highlight === "payees"} />
            {state.suppliers && <Suppliers list={state.suppliers} />}</>}
        </div>
        {state.suppliers && state.fixture === "reputation" && tab !== "payees" && <Suppliers list={state.suppliers} />}
        <Team agents={state.agents} />
        <p className="mt-6 flex items-center gap-2 text-micro text-ink-2"><span className="h-1 w-1 rounded-full bg-accent" aria-hidden="true" />
          {state.fixture ? "Replayed fixture · no chain calls" : `Live · ${state.network || "Sepolia testnet"}`}</p>
      </div>
    </div>
  );
}
