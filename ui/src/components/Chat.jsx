import { useState } from "react";
import { BookOpen, Send, Timer, User } from "lucide-react";
import { ActionCard, ModelDown, OwnerReceipt, PayeeCard, PayeeNotSaved, PayeeReceipt, QuestionCard, RefusalCard, TxReceipt, UntrustedBlock } from "./Cards.jsx";
import { Trace } from "./Trace.jsx";
import { Button, Chip, Prose } from "./ui.jsx";

const isMonitor = (e) => e.action?.origin?.kind === "monitor";

function cardsFor(turn, ctx) {
  const out = [];
  turn.events.forEach((e, i) => {
    const key = `${e.event}-${e.line ?? i}`;
    if (e.event === "verdict") {
      const v = e.verdict;
      if (v.allowed && v.needs_confirmation) {
        const pending = ctx.pendingLine != null && ctx.pendingLine === e.line;
        const confirmed = turn.events.some((x) => x.event === "confirmed") || ctx.confirmedLines.has(e.line);
        out.push(<ActionCard key={key} e={e} pending={pending} confirmed={confirmed} diff={turn.diff}
          disabled={ctx.halted || ctx.busy} onConfirm={ctx.onConfirm} onEdit={ctx.onEdit} />);
      } else if (!v.allowed) {
        out.push(<RefusalCard key={key} e={e} ownerWords={ctx.ownerWords} autonomous={isMonitor(e)} />);
      }
    } else if (e.event === "executed" || e.event === "tx_failed") {
      out.push(<TxReceipt key={key} e={e} autonomous={isMonitor(e)} />);
    } else if (e.event === "owner_command") {
      out.push(<OwnerReceipt key={key} e={e} />);
    } else if (e.event === "payee_check") {
      out.push(<PayeeCard key={key} e={e} pending={ctx.pendingPayeeLine != null && ctx.pendingPayeeLine === e.line}
        saved={ctx.savedPayees.has(e.address)} disabled={ctx.halted || ctx.busy} onConfirm={ctx.onConfirmPayee} />);
    } else if (e.event === "payee_saved") {
      out.push(<PayeeReceipt key={key} e={e} now={ctx.now} />);
    } else if (e.event === "payee_confirm_failed") {
      out.push(<PayeeNotSaved key={key} e={e} />);
    } else if (e.event === "coordinator_error") {
      out.push(<ModelDown key={key} e={e} disabled={ctx.halted || ctx.busy} onRetry={() => ctx.onRetry(turn.user)} />);
    }
  });
  return out;
}

export function Turn({ turn, ctx }) {
  const cards = cardsFor(turn, ctx);
  const owner = /^\/(attest|approve|dispute|resolve)\b/.test(turn.user || "");
  return (
    <article className="space-y-3" aria-label={turn.user ? `Turn: ${turn.user}` : "System event"}>
      {turn.user && (
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded bg-subtle px-4 py-2 text-base text-ink [overflow-wrap:anywhere]">
            <span className="sr-only">You said: </span>
            {owner && <Chip tone="accent" className="mr-2 border-ink text-ink">Owner command</Chip>}
            {turn.user}
          </div>
        </div>
      )}
      {turn.system && <p className="text-sm text-ink-2"><Chip tone="muted">Outside the agent</Chip> {turn.source}</p>}
      <div className="rounded bg-surface p-4 sm:p-6">
        <p className="mb-2 flex items-center gap-2 text-cap font-semibold uppercase tracking-wider text-ink-2">TR8DE</p>
        {turn.reply && <div className="[overflow-wrap:anywhere]"><Prose text={turn.reply} /></div>}
        {turn.untrusted?.map((u) => <div key={u.source} className="mt-3"><UntrustedBlock u={u} /></div>)}
        {turn.question && <div className="mt-3"><QuestionCard q={turn.question} /></div>}
        {cards.length > 0 && <div className="mt-3 space-y-3">{cards}</div>}
        {!turn.reply && !cards.length && turn.inflight && <p className="text-sm text-ink-2">Working on it. Each check ticks as it finishes.</p>}
        <Trace events={turn.events} inflight={turn.inflight} open={!!turn.inflight} />
        {turn.source && !turn.system && <p className="mt-2 text-cap text-ink-2">Replayed from {turn.source}</p>}
      </div>
    </article>
  );
}

export function Composer({ disabled, busy, value, setValue, onSend, onTick, inputRef }) {
  return (
    <form className="flex flex-col gap-2 rounded bg-surface p-3 sm:flex-row"
      onSubmit={(ev) => { ev.preventDefault(); if (value.trim()) onSend(value.trim()); }}>
      <label htmlFor="msg" className="sr-only">Message TR8DE</label>
      <input id="msg" ref={inputRef} value={value} onChange={(ev) => setValue(ev.target.value)} disabled={disabled}
        placeholder={disabled ? "Halted: actions are disabled" : "Ask TR8DE, or type /guide"}
        className="min-h-[44px] flex-1 rounded border border-accent bg-raised px-3 text-base text-ink placeholder:text-ink-2 disabled:opacity-60" />
      <div className="flex gap-2">
        <Button type="submit" disabled={disabled || busy || !value.trim()} className="flex-1 sm:flex-none"><Send size={16} aria-hidden="true" />Send</Button>
        <Button type="button" variant="ghost" onClick={onTick} disabled={disabled || busy} className="flex-1 sm:flex-none"><Timer size={16} aria-hidden="true" />Run monitor</Button>
      </div>
    </form>
  );
}

export const SUGGESTIONS = [
  "What's my balance and what deals are open?",
  "What is Lumen Textiles' delivery record?",
  "Can I afford a PHP 80,000 PO on 2026-10-30?",
  "Create escrow for Lumen PO-106, PHP 100,000, 20% down, delivery by 2026-10-30",
  "Release the balance for deal 6",
  "Save a new supplier, Kalinaw Crafts, payout 0x",
];

/** Recommended prompts. A click fills the box so the owner can edit before sending; /guide sends at once. */
export function Suggestions({ onPick, onSend, disabled }) {
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="Suggested prompts">
      <span className="text-cap text-ink-2">Try:</span>
      <button type="button" disabled={disabled} onClick={() => onSend("/guide")}
        className="inline-flex min-h-[32px] items-center gap-1 rounded-full border border-accent px-3 text-cap font-semibold text-ink hover:bg-subtle/40 disabled:opacity-50">
        <BookOpen size={12} aria-hidden="true" />/guide</button>
      {SUGGESTIONS.map((s) => (
        <button key={s} type="button" disabled={disabled} onClick={() => onPick(s)}
          className="min-h-[32px] max-w-full rounded-full border border-subtle px-3 text-left text-cap text-ink-2 hover:border-accent hover:text-ink disabled:opacity-50">
          {s}</button>
      ))}
    </div>
  );
}

export function EmptyChat() {
  return (
    <div className="rounded bg-surface p-6 text-ink-2">
      <p className="flex items-center gap-2 text-base text-ink"><User size={16} aria-hidden="true" />Tell TR8DE what to pay, and to whom.</p>
      <p className="mt-1 text-sm">For example: “Create escrow for Lumen PO-104, PHP 120,000, 30% down, delivery by 2026-10-25”. Every new deal comes back to you for a yes. Type <span className="font-mono text-ink">/guide</span> for everything TR8DE can do.</p>
    </div>
  );
}
