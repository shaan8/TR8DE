import { useState } from "react";
import { AlertTriangle, ArrowRight, Ban, CheckCircle2, CircleHelp, ExternalLink, FileWarning, KeyRound, Pencil, RotateCcw, ShieldAlert, XCircle } from "lucide-react";
import { Button, Card, Chip, Row } from "./ui.jsx";
import { KIND, addrUrl, chunk, parseMismatch, peso, short, txUrl, when } from "../lib.js";

const TIER_TONE = { 1: "ok", 2: "warn", 3: "bad" };
export const TierChip = ({ tier }) => <Chip tone={TIER_TONE[tier] || "muted"}>Tier {tier}</Chip>;

function TxLink({ hash }) {
  return (
    <a href={txUrl(hash)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-sm" title={hash}>
      {short(hash, 12)} <ExternalLink size={14} aria-hidden="true" /><span className="sr-only">(opens Etherscan)</span>
    </a>
  );
}

function CheckerLine({ checker }) {
  if (!checker) return null;
  return (
    <Row label="Checker">
      <span className="mr-2">{checker.approve ? <Chip tone="ok" icon={CheckCircle2}>Approved</Chip> : <Chip tone="bad" icon={XCircle}>Rejected</Chip>}</span>
      <span className="text-ink-2">{checker.reason}</span>
    </Row>
  );
}

/** Tier 2, in the design's approval card: the amount and split up front, every check one click away. */
export function ActionCard({ e, pending, confirmed, diff, disabled, onConfirm, onEdit }) {
  const c = e.card || {}, v = e.verdict, view = e.view || {};
  const cap = c.cap;
  const within = cap && c.down_pct <= cap.final_pct;
  const total = c.total_php ?? view.total_php, downPct = c.down_pct ?? view.down_payment_pct;
  const down = c.down_php ?? view.down_payment_php, bal = c.balance_php ?? view.balance_php;
  return (
    <div id={pending ? "pending-card" : undefined} aria-label="Approval needed" role="group"
      className="rounded-[9px] border border-[#4b5437] bg-raised p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-micro tracking-[0.12em] text-warn">
          <span className="h-1.5 w-1.5 rounded-full bg-warn" aria-hidden="true" />
          {confirmed ? "CONFIRMED BY YOU" : pending ? "YOUR APPROVAL NEEDED" : "SUPERSEDED"}
        </span>
        <span className="flex gap-1.5"><TierChip tier={v.tier} />{confirmed && <Chip tone="ok" icon={CheckCircle2}>Confirmed</Chip>}</span>
      </div>
      <div className="my-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">{c.supplier || view.supplier}</h3>
          <p className="text-micro text-ink-2">{KIND[view.kind]} · {c.po || view.po_ref} · deliver by {c.deliver_by || view.deliver_by}</p>
        </div>
        <strong className="text-right font-display text-[22px] font-medium tracking-[-0.02em]">{peso(total)}
          <span className="block font-sans text-micro font-normal tracking-normal text-ink-2">tPHP · full PO locked</span></strong>
      </div>
      <div className="grid grid-cols-2 gap-4 border-y border-subtle py-3.5">
        <div><span className="block text-micro text-ink-2">Down payment · {downPct}%</span><strong className="font-display text-[15px] font-medium">{peso(down)}</strong>
          {c.release_now && <span className="block text-micro text-ink-2">released right after creation</span>}</div>
        <div><span className="block text-micro text-ink-2">Held in escrow · {100 - (downPct || 0)}%</span><strong className="font-display text-[15px] font-medium">{peso(bal)}</strong>
          <span className="block text-micro text-ink-2">only after your /attest</span></div>
      </div>
      <p className="my-3.5 flex flex-wrap gap-x-5 gap-y-1 text-micro text-ok">
        <span>{e.intent?.ok ? "✓ Matches your words" : "✕ Intent mismatch"}</span>
        <span>{e.checker?.approve ? "✓ Checker approved" : "✕ Checker rejected"}</span>
        {cap && <span className={within ? "" : "text-bad"}>{within ? "✓" : "✕"} Deposit within {cap.final_pct}% cap</span>}
        <span className={c.forecast?.ok === false ? "text-warn" : ""}>{c.forecast?.ok === false ? "! Forecast shortfall" : "✓ No forecast shortfall"}</span>
      </p>
      {c.filled?.length > 0 && <p className="mb-3"><Chip tone="warn" icon={Pencil} wrap>Filled in by TR8DE, please check: {c.filled.join(", ")}</Chip></p>}

      {diff && (
        <div className="mb-4 rounded-md border border-accent/40 p-3.5" aria-label="Correction">
          <p className="mb-2 text-cap font-semibold">Changed from your first request</p>
          <p className="mb-2 text-micro text-ink-2">You first said: “{diff.against}”</p>
          <ul className="space-y-1">
            {diff.fields.map((f) => (
              <li key={f.field} className="flex flex-wrap items-center gap-2 text-cap">
                <span className="w-28 text-ink-2">{f.field}</span>
                <span className="text-bad line-through decoration-2">{f.from}</span>
                <ArrowRight size={14} aria-hidden="true" /><span className="sr-only">changed to</span>
                <span className="font-semibold text-ok">{f.to}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-micro"><RotateCcw size={14} aria-hidden="true" />Re-checked: {diff.rechecked.map((r) => <Chip key={r} tone="ok">{r}</Chip>)}</p>
        </div>
      )}

      {pending && (
        <div className="flex flex-wrap gap-2">
          <button onClick={onConfirm} disabled={disabled}
            className="flex min-h-[38px] flex-1 items-center justify-between gap-2 rounded-md bg-accent px-3.5 text-cap font-semibold text-accent-deep hover:bg-[#d9edbc] disabled:opacity-50">
            Review &amp; approve <span aria-hidden="true">↗</span></button>
          <button onClick={onEdit} disabled={disabled}
            className="min-h-[38px] rounded-md border border-subtle px-3.5 text-cap hover:border-accent hover:text-accent-text disabled:opacity-50">Edit terms</button>
        </div>
      )}
      <p className="mt-2.5 text-micro text-ink-2">{confirmed ? "Sent after your own yes." : "Nothing has moved yet. TR8DE sends it only after your own yes."}</p>

      <details className="mt-3 text-cap text-ink-2">
        <summary className="cursor-pointer py-2 hover:text-accent-text">View policy, liquidity &amp; independent checks <span aria-hidden="true" className="float-right">＋</span></summary>
        <dl className="mt-1 divide-y divide-line">
          <Row label="Supplier">
            <span className="font-semibold">{c.supplier || view.supplier}</span>
            {c.r != null && <> · <span className="font-mono">R = {c.r.toFixed(2)}</span></>}
            {c.record && <div className="text-micro text-ink-2">{c.record}</div>}
          </Row>
          {cap && (
            <Row label="Cap math">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono">
                <span>network {cap.network_pct}%</span>
                {cap.stranger_pct != null && <span>· stranger {cap.stranger_pct}% {cap.stranger_binds ? "(applies: new to you)" : "(does not bind)"}</span>}
                <span>· final <strong>{cap.final_pct}%</strong></span>
              </span>
              <span className="mt-1 flex items-center gap-2">
                {within ? <Chip tone="ok" icon={CheckCircle2}>Within cap</Chip> : <Chip tone="bad" icon={XCircle}>Over cap</Chip>}
                <span className="text-ink-2">{c.down_pct}% asked vs {cap.final_pct}% allowed</span>
              </span>
            </Row>
          )}
          <Row label="Forecast impact">
            {c.forecast?.ok === false ? (
              <span className="flex flex-wrap items-center gap-2"><Chip tone="warn" icon={AlertTriangle}>Shortfall</Chip>
                <span>short by <span className="font-mono">{peso(c.forecast.shortfall_php)}</span> on {c.forecast.date}</span></span>
            ) : <Chip tone="ok">No shortfall</Chip>}
          </Row>
          <Row label="Intent">{e.intent?.ok ? <Chip tone="ok" icon={CheckCircle2}>Matches your words</Chip> : <Chip tone="bad">Mismatch</Chip>}</Row>
          <CheckerLine checker={e.checker} />
          <Row label="Policy">
            <span className="mr-2"><TierChip tier={v.tier} /></span>
            <span className="text-ink-2">{v.reasons.join(" ")}</span>
            {v.flags?.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{v.flags.map((f) => <Chip key={f} tone="warn">{f}</Chip>)}</div>}
          </Row>
        </dl>
      </details>
    </div>
  );
}

/** Tier 3: the rule that refused, the flags, and no way to confirm. */
export function RefusalCard({ e, ownerWords, autonomous }) {
  const v = e.verdict, view = e.view || {};
  const mism = (e.intent?.mismatches || []).map(parseMismatch);
  return (
    <Card tone="bad" aria-label="Refused">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Chip tone="bad" icon={Ban}>Refused</Chip>
        <TierChip tier={v.tier} />
        {autonomous && <Chip tone="accent">Autonomous rule</Chip>}
        {(v.flags || []).map((f) => <Chip key={f} tone={f === "forecast_shortfall" ? "warn" : "bad"}>{f}</Chip>)}
      </div>
      <h3 className="mb-1 text-title font-semibold">{KIND[view.kind]}{view.po_ref ? ` · ${view.po_ref}` : view.deal_id ? ` · deal ${view.deal_id}` : ""} · {view.supplier}</h3>
      <p className="mb-4 text-sm text-ink-2">Not sent. There is no Confirm: Tier 3 cannot be overridden from chat.</p>

      {mism.length > 0 && (
        <div className="mb-4 rounded border border-bad p-4" aria-label="Intent mismatch">
          <p className="mb-2 flex items-center gap-2 text-sm font-semibold"><ShieldAlert size={16} aria-hidden="true" />Your words vs the drafted action</p>
          {ownerWords?.length > 0 && (
            <ul className="mb-3 space-y-1 text-sm text-ink-2">{ownerWords.map((w, i) => <li key={i}>You: “{w}”</li>)}</ul>
          )}
          <table className="w-full text-left text-sm">
            <thead><tr className="text-ink-2"><th className="py-1 font-medium">Field</th><th className="font-medium">You said</th><th className="font-medium">Drafted</th></tr></thead>
            <tbody>{mism.map((m) => (
              <tr key={m.field}>
                <td className="py-1 capitalize">{m.field}</td>
                <td className="font-mono">{m.said}</td>
                <td><mark className="rounded bg-bad px-1.5 font-mono font-semibold text-canvas">{m.drafted}</mark> <span className="sr-only">mismatch</span></td>
              </tr>))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mb-1 text-sm font-semibold">Rule that refused</p>
      <ol className="mb-3 list-decimal space-y-1 pl-5 text-sm">
        {v.reasons.filter((r) => !/needs your confirmation/.test(r)).map((r) => <li key={r}>{r}</li>)}
      </ol>
      <dl><CheckerLine checker={e.checker} /></dl>
    </Card>
  );
}

export function TxReceipt({ e, autonomous }) {
  const failed = e.event === "tx_failed";
  const a = e.action || {};
  return (
    <Card tone={failed ? "bad" : "ok"} aria-label={failed ? "Transaction reverted" : "Transaction receipt"}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {failed ? <Chip tone="bad" icon={XCircle}>Reverted</Chip> : <Chip tone="ok" icon={CheckCircle2}>Executed</Chip>}
        {autonomous && <Chip tone="accent">Autonomous</Chip>}
        {e.synthetic && <Chip tone="muted" icon={FileWarning}>From transcript, not the agent</Chip>}
      </div>
      <dl>
        <Row label="Action">{KIND[a.kind] || a.kind}{a.ref ? ` · ${a.ref}` : ""}</Row>
        {(e.deal_id || a.deal_id) && <Row label="Deal">#{e.deal_id || a.deal_id}</Row>}
        {e.block && <Row label="Block" mono>{e.block.toLocaleString("en-US")}</Row>}
        {failed && <Row label="Decoded"><span className="font-mono text-bad">{e.error}</span>{e.selector && <span className="text-ink-2"> · selector <span className="font-mono">{e.selector}</span></span>}</Row>}
        <Row label="Tx">{e.tx ? <TxLink hash={e.tx} /> : "none"}</Row>
        <Row label="Status">{failed ? "status 0, reverted by the contract; no funds moved" : "status 1, confirmed on-chain"}</Row>
      </dl>
      {e.note && <p className="mt-2 text-sm text-ink-2">{e.note}</p>}
    </Card>
  );
}

export function OwnerReceipt({ e }) {
  return (
    <Card tone="accent" className="border border-accent" aria-label="Owner-key action">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Chip tone="accent" icon={KeyRound}>Owner key</Chip>
        {e.ok ? <Chip tone="ok" icon={CheckCircle2}>Signed</Chip> : <Chip tone="bad">Failed</Chip>}
      </div>
      <p className="mb-2 text-sm text-ink-2">Signed with your own key, not the agent's. Only a typed slash command can do this.</p>
      <dl>
        <Row label="Command" mono>{e.command}</Row>
        <Row label="Tx">{e.tx ? <TxLink hash={e.tx} /> : e.error}</Row>
      </dl>
    </Card>
  );
}

export function QuestionCard({ q }) {
  return (
    <Card tone="accent" aria-label="Clarifying question">
      <div className="mb-2 flex items-center gap-2"><Chip tone="accent" icon={CircleHelp}>Needs one detail</Chip></div>
      <p className="text-base">Missing: <strong className="rounded bg-canvas px-1.5">{q.missing}</strong></p>
      <p className="mt-1 text-sm text-ink-2">{q.why} No action was drafted.</p>
    </Card>
  );
}

export function UntrustedBlock({ u }) {
  return (
    <figure className="rounded border-2 border-dashed border-warn bg-canvas p-4" aria-label="Untrusted text from chain">
      <figcaption className="mb-2 flex flex-wrap items-center gap-2 text-sm font-semibold">
        <ShieldAlert size={16} className="text-warn" aria-hidden="true" />From chain, treated as data
        <span className="font-mono text-cap text-ink-2">{u.source}</span>
        {u.flags.map((f) => <Chip key={f} tone="bad">{f}</Chip>)}
      </figcaption>
      <blockquote className="break-all font-mono text-sm text-ink">“{u.text}”</blockquote>
      <p className="mt-2 text-cap text-ink-2">The input guard tagged this PO note. No tool call followed from it.</p>
    </figure>
  );
}

export function ModelDown({ e, onRetry, disabled }) {
  const code = /Error code: (\d+)/.exec(e.error)?.[1];
  return (
    <div role="status" className="rounded border border-warn bg-raised p-4">
      <p className="flex items-center gap-2 font-semibold"><AlertTriangle size={16} className="text-warn" aria-hidden="true" />The assistant model is unavailable{code ? ` (rate limit ${code})` : ""}.</p>
      <p className="mt-1 text-sm text-ink-2">Nothing was drafted, nothing moved. The monitor and your owner commands still work.</p>
      <Button variant="ghost" className="mt-3" onClick={onRetry} disabled={disabled}><RotateCcw size={16} aria-hidden="true" />Retry</Button>
    </div>
  );
}

const SEV = (c) => (c.ok ? { tone: "ok", Icon: CheckCircle2, word: "Pass" } : c.severity === "flag"
  ? { tone: "warn", Icon: AlertTriangle, word: "Check" } : { tone: "bad", Icon: XCircle, word: "Fail" });
const RULE_LABEL = {
  format: "Address format", checksum: "Checksum", provenance: "You typed it", address_also_in_chain_text: "Also in chain text",
  name_filled_by_tiwala: "Name source", reserved: "Not a wallet role", blocklist: "Blocklist", duplicate: "Not saved yet",
  payout_address_change: "Payout change", lookalike_address: "Lookalike address", lookalike_name: "Lookalike name",
  similar_name: "Similar name",
};

function Address({ a }) {
  return (
    <a href={addrUrl(a)} target="_blank" rel="noreferrer" className="inline-flex flex-wrap items-center gap-x-2 font-mono text-base" title={a}>
      {chunk(a)} <ExternalLink size={14} aria-hidden="true" /><span className="sr-only">(opens Etherscan)</span>
    </a>
  );
}

/** A drafted payee: every check, then the owner types the last 4 characters and their key signs. */
export function PayeeCard({ e, pending, saved, disabled, onConfirm }) {
  const [code, setCode] = useState("");
  const ok = /^[0-9a-f]{4}$/i.test(code);
  const change = e.kind === "address_change";
  const hours = e.delay_s ? (e.delay_s >= 3600 ? `${e.delay_s / 3600}-hour` : `${e.delay_s}-second`) : "";
  return (
    <Card tone={e.allowed ? "warn" : "bad"} id={pending ? "pending-payee" : undefined} aria-label={e.allowed ? "Payee approval needed" : "Payee refused"}>
      <div className="mb-4 flex flex-wrap items-center gap-2">
        {!e.allowed ? <Chip tone="bad" icon={Ban}>Refused</Chip> : saved ? <Chip tone="accent" icon={KeyRound}>Signed by owner key</Chip>
          : <Chip tone="warn" icon={KeyRound}>Owner key needed</Chip>}
        <Chip tone={change ? "warn" : "accent"}>{change ? "Payout address change" : "New payee"}</Chip>
        {saved && <Chip tone="ok" icon={CheckCircle2}>Saved</Chip>}
        {e.allowed && !pending && !saved && <Chip tone="muted">Not confirmed</Chip>}
      </div>
      <h3 className="mb-1 text-title font-semibold">{change ? "Change payout address" : "Save payee"} · {e.name || "unnamed"}</h3>
      <p className="mb-4 text-sm text-ink-2">{saved ? "Saved after you typed the last 4 characters and your key signed it."
        : e.allowed ? "Nothing is saved yet. Code ran every check below; the agent cannot save a payee, only your key can."
        : "Not saved. There is no Confirm: a failed payee check cannot be overridden from chat."}</p>
      <dl className="divide-y divide-subtle/60">
        <Row label="Address">{/^0x[0-9a-fA-F]{40}$/.test(e.address) ? <Address a={e.address} /> : <span className="font-mono">{e.address}</span>}</Row>
        {e.replaces && <Row label="Replaces"><span className="font-mono text-ink-2 line-through">{chunk(e.replaces)}</span></Row>}
        <Row label="Checks">
          <ul className="space-y-1.5">
            {e.checks.map((c) => {
              const s = SEV(c);
              return (
                <li key={c.rule} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-2">
                  <Chip tone={s.tone} icon={s.Icon} className="mt-0.5">{s.word}</Chip>
                  <span><span className="font-semibold">{RULE_LABEL[c.rule] || c.rule}</span> <span className={c.ok ? "text-ink-2" : ""}>{c.detail}</span></span>
                </li>
              );
            })}
          </ul>
        </Row>
        {e.allowed && <Row label="After you sign">Payable after the wallet's {hours} waiting period, enforced by the contract.</Row>}
      </dl>
      {pending && (
        <form className="mt-6 flex flex-wrap items-end gap-3" onSubmit={(ev) => { ev.preventDefault(); if (ok) onConfirm(code); }}>
          <label className="text-sm">
            <span className="mb-1 block text-ink-2">Check the address against the supplier's invoice, then type its last 4 characters</span>
            <input value={code} onChange={(ev) => setCode(ev.target.value.trim().slice(0, 4))} maxLength={4} autoComplete="off" spellCheck={false}
              className="w-28 rounded border border-subtle bg-canvas px-3 py-2 font-mono text-base text-ink" aria-label="Last 4 characters of the address" />
          </label>
          <Button type="submit" disabled={disabled || !ok}><KeyRound size={16} aria-hidden="true" />Sign with owner key</Button>
        </form>
      )}
    </Card>
  );
}

export function PayeeReceipt({ e, now }) {
  const waiting = e.active_at && now && e.active_at > now;
  return (
    <Card tone="ok" aria-label="Payee saved">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Chip tone="accent" icon={KeyRound}>Owner key</Chip><Chip tone="ok" icon={CheckCircle2}>Saved on-chain</Chip>
        {waiting && <Chip tone="warn">Waiting period</Chip>}
      </div>
      <dl>
        <Row label="Payee">{e.name}</Row>
        <Row label="Address"><Address a={e.address} /></Row>
        <Row label="Tx"><TxLink hash={e.tx} /></Row>
        {e.remove_tx && <Row label="Old address removed"><TxLink hash={e.remove_tx} /></Row>}
        <Row label="Payable from"><span className="font-mono">{when(e.active_at)}</span> <span className="text-ink-2">(Manila time; the contract refuses deals before this)</span></Row>
      </dl>
    </Card>
  );
}

export function PayeeNotSaved({ e }) {
  return (
    <div role="status" className="rounded border border-bad bg-raised p-4 text-sm">
      <p className="flex items-center gap-2 font-semibold"><XCircle size={16} className="text-bad" aria-hidden="true" />Not saved: {e.reason}.</p>
      <p className="mt-1 text-ink-2">Nothing was signed. Ask again to start over.</p>
    </div>
  );
}
