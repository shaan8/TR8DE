import { AlertTriangle, Ban, Bot, CheckCircle2, ExternalLink, KeyRound, ShieldAlert } from "lucide-react";
import clsx from "clsx";
import { Trace } from "./Trace.jsx";
import { Chip } from "./ui.jsx";
import { KIND, RULE, peso, short, txUrl, when } from "../lib.js";

function Entry({ a, highlight }) {
  const tx = a.tx && (
    <a href={txUrl(a.tx)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-micro" title={a.tx}>
      {short(a.tx)} <ExternalLink size={12} aria-hidden="true" /><span className="sr-only">(opens Etherscan)</span>
    </a>
  );
  const ok = a.status === "executed";
  let title, body, who;
  if (a.type === "autonomous") {
    title = `${KIND[a.kind] || a.kind} · deal ${a.deal_id}`;
    body = <>Rule fired: {RULE[a.rule] || a.rule} (<span className="font-mono">{a.rule}</span>)
      {a.reasons && <span className="block text-bad">{a.reasons[0]}</span>}</>;
    who = <><Chip tone="accent" icon={Bot}>Autonomous</Chip>{a.tier && <Chip tone={a.tier === 1 ? "ok" : "bad"}>Tier {a.tier}</Chip>}
      {ok ? <Chip tone="ok" icon={CheckCircle2}>Executed</Chip> : <Chip tone="bad" icon={Ban}>Refused</Chip>}</>;
  } else {
    title = a.command;
    body = "Signed by you with the owner key, not the agent.";
    who = <><Chip tone="accent" icon={KeyRound}>Owner key</Chip>{ok ? <Chip tone="ok">Signed</Chip> : <Chip tone="bad">Failed</Chip>}</>;
  }
  return (
    <li className={clsx("flex gap-3 border-b border-line py-4", highlight && "rounded ring-2 ring-warn")}>
      <span className={clsx("grid h-6 w-6 shrink-0 place-items-center rounded-full border text-micro",
        ok ? "border-subtle bg-accent-soft text-accent-text" : "border-warn/50 bg-[#2e2c1d] text-warn")} aria-hidden="true">{ok ? "✓" : "!"}</span>
      <div className="min-w-0 flex-1">
        <h4 className="text-cap font-medium [overflow-wrap:anywhere]">{title}</h4>
        <p className="mt-1 text-micro leading-5 text-ink-2">{body}</p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">{who}</div>
        {tx && <p className="mt-1.5">{tx}{a.block ? <span className="font-mono text-micro text-ink-2"> · block {a.block.toLocaleString("en-US")}</span> : null}</p>}
        {a.events && <Trace events={a.events} open={highlight} label="Trace" />}
      </div>
      <time className="shrink-0 whitespace-nowrap pt-0.5 font-mono text-micro text-ink-2">{when(a.ts).slice(5)}</time>
    </li>
  );
}

export function FeedList({ items, highlight }) {
  return items?.length ? (
    <ol aria-label="Activity">{items.map((a, i) => <Entry key={a.line ?? i} a={a} highlight={highlight && i === 0} />)}</ol>
  ) : <p className="py-6 text-sm text-ink-2">No autonomous or owner-key actions yet. They appear here as they happen.</p>;
}

/** The design's amber bar: one row per thing that waits on the owner. */
export function NeedsYou({ pending, payee, alerts, highlight, onReview }) {
  const items = [];
  if (payee) {
    items.push(
      <li key="payee"><button onClick={() => onReview("pending-payee")} className="flex w-full flex-wrap items-center justify-between gap-2 rounded-md border border-warn/40 bg-[#27271a] px-3 py-2.5 text-left">
        <span className="flex items-center gap-2 text-cap text-warn"><KeyRound size={14} aria-hidden="true" />
          {payee.kind === "address_change" ? "Payout change" : "New payee"}: {payee.name} · <span className="font-mono">{payee.address.slice(0, 6)}…{payee.address.slice(-4)}</span></span>
        <strong className="text-micro font-medium text-warn">Review ↗</strong>
      </button></li>,
    );
  }
  if (pending) {
    const c = pending.card || {};
    items.push(
      <li key="p"><button onClick={() => onReview()} className="flex w-full flex-wrap items-center justify-between gap-2 rounded-md border border-warn/40 bg-[#27271a] px-3 py-2.5 text-left">
        <span className="flex items-center gap-2 text-cap text-warn"><span className="h-1.5 w-1.5 rounded-full bg-warn" aria-hidden="true" />
          1 payment needs your approval: {c.supplier} · {c.po} · <span className="font-mono">{peso(c.total_php)}</span></span>
        <strong className="text-micro font-medium text-warn">Review payment ↗</strong>
      </button></li>,
    );
  }
  for (const a of alerts || []) {
    items.push(
      <li key={a.kind} className={clsx("flex flex-wrap items-center gap-2 rounded-md border px-3 py-2.5 text-cap",
        a.kind === "halt" ? "border-bad/60 bg-[#2b1c18] text-bad" : "border-warn/40 bg-[#27271a] text-warn")}>
        {a.kind === "halt" ? <ShieldAlert size={14} aria-hidden="true" /> : <AlertTriangle size={14} aria-hidden="true" />}
        {a.kind === "shortfall"
          ? <span>Planned POs leave you <span className="font-mono font-semibold">{peso(a.amount_php)}</span> short on <strong>{a.date}</strong>. Delay a PO or top up.</span>
          : <span>{a.text}</span>}
      </li>,
    );
  }
  if (!items.length) {
    return (
      <section aria-label="Needs you" className={clsx("px-4 md:px-9", highlight && "ring-2 ring-warn")}>
        <p className="flex items-center gap-2 text-micro text-ink-2"><CheckCircle2 size={14} className="text-ok" aria-hidden="true" />Nothing needs you.</p>
      </section>
    );
  }
  return (
    <section aria-label="Needs you" className={clsx("px-4 md:px-9", highlight && "ring-2 ring-warn")}>
      <ul className="space-y-2">{items}</ul>
    </section>
  );
}
