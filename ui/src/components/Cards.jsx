import { AlertTriangle, ArrowRight, Ban, CheckCircle2, CircleHelp, ExternalLink, FileWarning, KeyRound, Pencil, RotateCcw, ShieldAlert, XCircle } from "lucide-react";
import { Button, Card, Chip, Row } from "./ui.jsx";
import { KIND, parseMismatch, peso, short, txUrl } from "../lib.js";

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

/** Tier 2: everything the owner needs to say yes, plus Confirm / Edit. */
export function ActionCard({ e, pending, confirmed, diff, disabled, onConfirm, onEdit }) {
  const c = e.card || {}, v = e.verdict, view = e.view || {};
  const cap = c.cap;
  const within = cap && c.down_pct <= cap.final_pct;
  return (
    <Card tone="warn" id={pending ? "pending-card" : undefined} aria-label="Approval needed">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Chip tone="warn" icon={AlertTriangle}>Approval needed</Chip>
        <TierChip tier={v.tier} />
        {confirmed && <Chip tone="ok" icon={CheckCircle2}>Confirmed</Chip>}
        {!pending && !confirmed && <Chip tone="muted">Superseded</Chip>}
      </div>
      <h3 className="mb-1 text-title font-semibold">{KIND[view.kind]} · {c.po || view.po_ref}</h3>
      <p className="mb-4 text-sm text-ink-2">Nothing has moved yet. Tiwala sends it only after your own yes.</p>

      {diff && (
        <div className="mb-4 rounded border border-accent p-4" aria-label="Correction">
          <p className="mb-2 text-sm font-semibold">Changed from your first request</p>
          <p className="mb-2 text-sm text-ink-2">You first said: “{diff.against}”</p>
          <ul className="space-y-1">
            {diff.fields.map((f) => (
              <li key={f.field} className="flex flex-wrap items-center gap-2 text-sm">
                <span className="w-28 text-ink-2">{f.field}</span>
                <span className="text-bad line-through decoration-2">{f.from}</span>
                <ArrowRight size={14} aria-hidden="true" /><span className="sr-only">changed to</span>
                <span className="font-semibold text-ok">{f.to}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 flex flex-wrap items-center gap-2 text-sm"><RotateCcw size={14} aria-hidden="true" />Re-checked: {diff.rechecked.map((r) => <Chip key={r} tone="ok">{r}</Chip>)}</p>
        </div>
      )}

      <dl className="divide-y divide-subtle/60">
        <Row label="Supplier">
          <span className="font-semibold">{c.supplier || view.supplier}</span>
          {c.r != null && <> · <span className="font-mono">R = {c.r.toFixed(2)}</span></>}
          {c.record && <div className="text-cap text-ink-2">{c.record}</div>}
        </Row>
        <Row label="Locked now"><span className="font-mono">{peso(c.total_php ?? view.total_php)}</span> <span className="text-ink-2">(full PO, held in escrow)</span></Row>
        <Row label="Down payment">
          <span className="font-mono">{c.down_pct ?? view.down_payment_pct}% = {peso(c.down_php ?? view.down_payment_php)}</span>
          {c.release_now && <span className="text-ink-2">, released right after creation</span>}
        </Row>
        <Row label="Balance"><span className="font-mono">{peso(c.balance_php ?? view.balance_php)}</span> <span className="text-ink-2">only after your delivery attestation</span></Row>
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
        <Row label="Deliver by">
          {c.deliver_by || view.deliver_by}
          {c.filled?.length > 0 && <div className="mt-1"><Chip tone="warn" icon={Pencil} wrap>Filled in by Tiwala, please check: {c.filled.join(", ")}</Chip></div>}
        </Row>
        <Row label="Intent">{e.intent?.ok ? <Chip tone="ok" icon={CheckCircle2}>Matches your words</Chip> : <Chip tone="bad">Mismatch</Chip>}</Row>
        <CheckerLine checker={e.checker} />
        <Row label="Policy">
          <span className="mr-2"><TierChip tier={v.tier} /></span>
          <span className="text-ink-2">{v.reasons.join(" ")}</span>
          {v.flags?.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{v.flags.map((f) => <Chip key={f} tone="warn">{f}</Chip>)}</div>}
        </Row>
      </dl>

      {pending && (
        <div className="mt-6 flex flex-wrap gap-3">
          <Button onClick={onConfirm} disabled={disabled}><CheckCircle2 size={16} aria-hidden="true" />Confirm</Button>
          <Button variant="ghost" onClick={onEdit} disabled={disabled}><Pencil size={16} aria-hidden="true" />Edit</Button>
        </div>
      )}
    </Card>
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
        <Row label="Status">{failed ? "status 0, reverted by the contract; no funds moved" : "status 1, confirmed on Sepolia"}</Row>
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
