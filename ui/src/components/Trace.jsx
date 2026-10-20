import { useState } from "react";
import { Bot, ChevronDown, ChevronRight, KeyRound, Link2, ShieldCheck, Loader2, Circle } from "lucide-react";
import { KIND, short, txUrl } from "../lib.js";

const WHO = {
  llm: { icon: Bot, label: "LLM" },
  code: { icon: ShieldCheck, label: "Code" },
  chain: { icon: Link2, label: "Chain" },
  owner: { icon: KeyRound, label: "Owner" },
};

const ok = (s) => <span className="font-semibold text-ok">{s}</span>;
const bad = (s) => <span className="font-semibold text-bad">{s}</span>;
const muted = (s) => <span className="text-ink-2">{s}</span>;
const tx = (h) => h && <a href={txUrl(h)} target="_blank" rel="noreferrer" className="font-mono">{short(h)}</a>;

/** One line per pipeline step, labelled by who acted. */
export function steps(events) {
  const out = [];
  for (const e of events) {
    const k = e.event;
    if (k === "user_message") {
      const f = e.flags || [];
      out.push(["code", "Input guard", f.length ? bad(`flagged: ${f.join(", ")}`) : <>{ok("clean")}{muted(", tagged as owner input")}</>]);
    } else if (k === "tool_call") {
      const args = Object.entries(e.args || {}).map(([a, v]) => `${a}=${v}`).join(", ");
      out.push(["llm", "Coordinator", <>called <code className="font-mono text-cap">{e.name}({args})</code></>]);
    } else if (k === "verdict") {
      const v = e.verdict, i = e.intent || {}, c = e.checker || {};
      out.push(["llm", "Coordinator", <>drafted <strong>{KIND[e.view?.kind] || e.view?.kind} · {e.view?.supplier}</strong></>]);
      out.push(["code", "Intent verifier", i.ok ? ok("matches your words") : bad(`mismatch: ${(i.mismatches || []).join("; ")}`)]);
      out.push(["llm", "Checker", <>{c.approve ? ok("approved") : bad("rejected")} {muted(c.reason)}</>]);
      out.push(["code", "Policy engine", <>Tier {v.tier} · {!v.allowed ? bad("refused") : v.needs_confirmation ? <span className="font-semibold text-warn">needs your confirmation</span> : ok("allowed")}
        {v.flags?.length ? muted(` · flags: ${v.flags.join(", ")}`) : null}</>]);
    } else if (k === "confirmed") {
      out.push(["owner", "Owner", <>confirmed in their own words; policy re-run on fresh chain state: {e.verdict?.allowed ? ok("allowed") : bad("refused")}</>]);
    } else if (k === "executed") {
      out.push(["chain", "Gate + signer", <>authorized, simulated, sent {tx(e.tx)}{e.deal_id ? ` · deal ${e.deal_id}` : ""}</>]);
    } else if (k === "tx_failed") {
      out.push(["chain", "Contract", <>{bad("reverted")} {e.error} {tx(e.tx)}</>]);
    } else if (k === "owner_command") {
      out.push(["owner", "Owner key", <>{e.command} {e.ok ? ok("sent") : bad(e.error)} {tx(e.tx)}</>]);
    } else if (k === "payee_check") {
      const failed = (e.checks || []).filter((c) => !c.ok && c.severity === "refuse").map((c) => c.rule);
      out.push(["llm", "Coordinator", <>drafted <strong>save payee · {e.name}</strong></>]);
      out.push(["code", "Payee checks", e.allowed ? <>{ok(`${(e.checks || []).filter((c) => c.ok).length} passed`)}{e.flags?.length ? muted(` · flags: ${e.flags.join(", ")}`) : null}</>
        : bad(`refused: ${failed.join(", ")}`)]);
    } else if (k === "payee_confirmed") {
      out.push(["owner", "Owner", <>typed the last 4 characters; checks re-run: {e.allowed ? ok("pass") : bad("refused")}</>]);
    } else if (k === "payee_confirm_failed") {
      out.push(["owner", "Owner", bad(`not saved: ${e.reason}`)]);
    } else if (k === "payee_saved") {
      out.push(["owner", "Owner key", <>addSupplier {ok("signed")} {tx(e.tx)}{e.remove_tx ? <> · removeSupplier {tx(e.remove_tx)}</> : null}</>]);
    } else if (k === "coordinator_error") {
      out.push(["llm", "Coordinator", <>{bad("unavailable")} {muted(String(e.error).slice(0, 90) + "…")}</>]);
    } else if (k === "monitor_tick") {
      out.push(["code", "Monitor tick", `${(e.notes || []).length} note(s)`]);
    } else if (k === "monitor_halt") {
      out.push(["code", "Monitor tick", bad("halted: wallet underfunded")]);
    }
  }
  return out;
}

const PENDING = [["code", "Intent verifier"], ["llm", "Checker"], ["code", "Policy engine"], ["chain", "Gate + signer"]];

export function TraceList({ events, inflight }) {
  const list = steps(events);
  return (
    <ol className="relative ml-1.5 space-y-2 border-l border-subtle pl-4">
      {list.map(([who, name, body], i) => {
        const W = WHO[who];
        return (
          <li key={i} className="text-cap leading-5 text-ink">
            <span className="mr-1 inline-flex items-center gap-1 rounded border border-subtle px-1.5 text-micro text-ink-2">
              <W.icon size={12} aria-hidden="true" />{W.label}
            </span>
            <span className="font-semibold">{name}</span> · {body}
          </li>
        );
      })}
      {inflight && PENDING.map(([who, name], i) => {
        const W = WHO[who];
        return (
          <li key={`p${i}`} className="text-cap leading-5 text-ink-2" aria-live={i === 0 ? "polite" : undefined}>
            <span className="mr-1 inline-flex items-center gap-1 rounded border border-subtle px-1.5 text-micro">
              <W.icon size={12} aria-hidden="true" />{W.label}
            </span>
            <span className="font-semibold">{name}</span> ·{" "}
            {i === 0 ? <span className="inline-flex items-center gap-1 text-warn"><Loader2 size={12} className="pulse" aria-hidden="true" />running</span>
              : <span className="inline-flex items-center gap-1"><Circle size={10} aria-hidden="true" />waiting</span>}
          </li>
        );
      })}
    </ol>
  );
}

/** Collapsible per-action agent trace. */
export function Trace({ events, inflight, open: initial = false, label = "Agent trace" }) {
  const [open, setOpen] = useState(initial || !!inflight);
  const n = steps(events).length;
  if (!n && !inflight) return null;
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <div className="mt-3">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
        className="inline-flex items-center gap-2 text-micro text-ink-2 hover:text-accent-text">
        <span className={inflight ? "pulse text-warn" : "text-accent-text"} aria-hidden="true">{inflight ? "◷" : "✓"}</span>
        {label === "Agent trace" ? (inflight ? "Running checks" : "Checks complete") : label}
        <span className="text-ink-2">{n} step{n === 1 ? "" : "s"} · who acted</span>
        <Icon size={13} aria-hidden="true" />
      </button>
      {open && <div className="mt-3"><TraceList events={events} inflight={inflight} /></div>}
    </div>
  );
}
