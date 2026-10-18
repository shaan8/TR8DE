import { AlertTriangle, Ban, Bot, CheckCircle2, ExternalLink, KeyRound, Link2, ShieldAlert } from "lucide-react";
import clsx from "clsx";
import { Trace } from "./Trace.jsx";
import { Button, Chip, Panel } from "./ui.jsx";
import { KIND, RULE, peso, short, txUrl, when } from "../lib.js";

function Entry({ a, highlight }) {
  const time = <span className="font-mono text-cap text-ink-2">{when(a.ts).slice(5)}</span>;
  const tx = a.tx && (
    <a href={txUrl(a.tx)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-cap" title={a.tx}>
      {short(a.tx)} <ExternalLink size={12} aria-hidden="true" /><span className="sr-only">(opens Etherscan)</span>
    </a>
  );
  let head, body;
  if (a.type === "autonomous") {
    head = <><Chip tone="accent" icon={Bot}>Autonomous</Chip>{a.tier && <Chip tone={a.tier === 1 ? "ok" : "bad"}>Tier {a.tier}</Chip>}
      {a.status === "executed" ? <Chip tone="ok" icon={CheckCircle2}>Executed</Chip> : <Chip tone="bad" icon={Ban}>Refused</Chip>}</>;
    body = <>
      <p className="text-sm"><span className="font-semibold">{KIND[a.kind]} · deal {a.deal_id}</span></p>
      <p className="text-cap text-ink-2">Rule fired: {RULE[a.rule] || a.rule} (<span className="font-mono">{a.rule}</span>)</p>
      {a.reasons && <p className="text-cap text-bad">{a.reasons[0]}</p>}
    </>;
  } else if (a.type === "owner") {
    head = <><Chip tone="accent" icon={KeyRound} className="border-ink text-ink">Owner key</Chip>{a.status === "executed" ? <Chip tone="ok">Signed</Chip> : <Chip tone="bad">Failed</Chip>}</>;
    body = <p className="text-sm"><span className="font-mono font-semibold">{a.command}</span> <span className="text-ink-2">signed by you, not the agent</span></p>;
  } else {
    head = <Chip tone="ok" icon={Link2}>{a.status === "account_linked" ? "Account linked" : "Account unlinked"}</Chip>;
    body = <p className="text-sm">{a.provider} <span className="text-ink-2">· read-only · link {a.link_id}</span></p>;
  }
  return (
    <li className={clsx("rounded bg-raised p-3", highlight && "ring-2 ring-warn")}>
      <div className="mb-1 flex flex-wrap items-center gap-1.5">{head}<span className="ml-auto">{time}</span></div>
      {body}
      {tx && <p className="mt-1">{tx}{a.block ? <span className="font-mono text-cap text-ink-2"> · block {a.block.toLocaleString("en-US")}</span> : null}</p>}
      {a.events && <Trace events={a.events} open={highlight} label="Trace" />}
    </li>
  );
}

export function Feed({ items, highlight }) {
  return (
    <Panel title="Activity" action={<span className="text-cap text-ink-2">Autonomous and owner-key, newest first</span>}>
      {items.length ? (
        <ol className="space-y-2">{items.map((a, i) => <Entry key={a.line} a={a} highlight={highlight && i === 0} />)}</ol>
      ) : <p className="text-sm text-ink-2">No autonomous or owner-key actions yet.</p>}
    </Panel>
  );
}

export function NeedsYou({ pending, alerts, highlight, onReview }) {
  const items = [];
  if (pending) {
    const c = pending.card || {};
    items.push(
      <li key="p" className="flex flex-wrap items-center gap-3 rounded bg-raised p-3">
        <Chip tone="warn" icon={AlertTriangle}>Approval</Chip>
        <span className="flex-1 text-sm">{c.supplier} · {c.po} · <span className="font-mono">{peso(c.total_php)}</span>, {c.down_pct}% down</span>
        <Button variant="ghost" className="min-h-[36px]" onClick={onReview}>Review</Button>
      </li>,
    );
  }
  for (const a of alerts) {
    items.push(
      <li key={a.kind} className={clsx("flex flex-wrap items-center gap-3 rounded bg-raised p-3", a.kind === "halt" && "border border-bad")}>
        {a.kind === "halt" ? <Chip tone="bad" icon={ShieldAlert}>Halted</Chip> : <Chip tone="warn" icon={AlertTriangle}>Shortfall</Chip>}
        <span className="flex-1 text-sm">{a.kind === "shortfall"
          ? <>Planned POs leave you <span className="font-mono font-semibold">{peso(a.amount_php)}</span> short on <span className="font-semibold">{a.date}</span>. Delay a PO or top up.</>
          : a.text}</span>
      </li>,
    );
  }
  return (
    <section aria-label="Needs you" className={clsx("rounded bg-surface p-4", highlight && "ring-2 ring-warn")}>
      <h2 className="mb-2 text-cap font-semibold uppercase tracking-wider text-ink-2">Needs you</h2>
      {items.length ? <ul className="space-y-2">{items}</ul>
        : <p className="flex items-center gap-2 text-sm"><CheckCircle2 size={16} className="text-ok" aria-hidden="true" />Nothing needs you.</p>}
    </section>
  );
}
