import { ArrowUp, BookOpen, Timer } from "lucide-react";
import { ActionCard, ModelDown, OwnerReceipt, PayeeCard, PayeeNotSaved, PayeeReceipt, QuestionCard, RefusalCard, TxReceipt, UntrustedBlock } from "./Cards.jsx";
import { Trace } from "./Trace.jsx";
import { Chip, Prose } from "./ui.jsx";

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

export function AgentLabel({ note = "Your finance agent" }) {
  return (
    <p className="flex items-center gap-2.5 text-cap font-semibold">
      <span className="grid h-6 w-6 place-items-center rounded-md border border-subtle bg-accent-soft text-[18px] leading-none text-accent-text" aria-hidden="true">✳</span>
      TR8DE <span className="text-micro font-normal text-ink-2">{note}</span>
    </p>
  );
}

export function Turn({ turn, ctx }) {
  const cards = cardsFor(turn, ctx);
  const owner = /^\/(attest|approve|dispute|resolve|limits|freeze|unfreeze|anchor)\b/.test(turn.user || "");
  return (
    <article className="space-y-5" aria-label={turn.user ? `Turn: ${turn.user}` : "System event"}>
      {turn.user && (
        <div className="flex items-start gap-2.5">
          <span className="grid h-[25px] w-[25px] shrink-0 place-items-center rounded-full bg-subtle text-micro text-ink" aria-hidden="true">O</span>
          <div className="max-w-[85%] rounded-[0_10px_10px_10px] border border-line bg-raised px-4 py-3 text-sm leading-[1.8] text-ink [overflow-wrap:anywhere]">
            <span className="sr-only">You said: </span>
            {owner && <Chip tone="accent" className="mr-2">Owner command</Chip>}
            {turn.user}
          </div>
        </div>
      )}
      {turn.system && <p className="text-sm text-ink-2"><Chip tone="muted">Outside the agent</Chip> {turn.source}</p>}
      <div>
        <AgentLabel />
        <Trace events={turn.events} inflight={turn.inflight} open={!!turn.inflight} />
        {turn.reply && <div className="mt-4 [overflow-wrap:anywhere]"><Prose text={turn.reply} /></div>}
        {turn.untrusted?.map((u) => <div key={u.source} className="mt-4"><UntrustedBlock u={u} /></div>)}
        {turn.question && <div className="mt-4"><QuestionCard q={turn.question} /></div>}
        {cards.length > 0 && <div className="mt-5 space-y-4">{cards}</div>}
        {!turn.reply && !cards.length && turn.inflight && <p className="mt-4 flex items-center gap-2 text-sm text-accent-text"><span className="pulse h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />Reviewing your request. Each check ticks as it finishes.</p>}
        {turn.source && !turn.system && <p className="mt-3 text-micro text-ink-2">Replayed from {turn.source}</p>}
      </div>
    </article>
  );
}

export function Composer({ disabled, busy, value, setValue, onSend, onTick, inputRef, model }) {
  const submit = () => { if (value.trim() && !busy && !disabled) onSend(value.trim()); };
  return (
    <form className="rounded-[10px] border border-[#46513b] bg-[#1b2118] p-3.5 shadow-[0_4px_25px_#0002] focus-within:border-[#8caa6a]"
      onSubmit={(ev) => { ev.preventDefault(); submit(); }}>
      <label htmlFor="msg" className="sr-only">Message TR8DE</label>
      <textarea id="msg" ref={inputRef} rows={2} value={value} onChange={(ev) => setValue(ev.target.value)} disabled={disabled}
        onKeyDown={(ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); submit(); } }}
        placeholder={disabled ? "Halted: actions are disabled" : "Ask your agent to pay, negotiate, or check your funds. Type /guide for everything"}
        className="w-full resize-none bg-transparent text-sm leading-[1.7] text-ink outline-none placeholder:text-ink-2 disabled:opacity-60" />
      <div className="mt-1.5 flex flex-wrap items-center gap-3">
        <button type="button" onClick={onTick} disabled={disabled || busy}
          className="inline-flex items-center gap-1.5 text-micro text-ink-2 hover:text-accent-text disabled:opacity-50"><Timer size={14} aria-hidden="true" />Run monitor</button>
        <span className="ml-auto flex items-center gap-1.5 text-micro text-accent-text"><span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />{model || "Coordinator"}</span>
        <button type="submit" disabled={disabled || busy || !value.trim()} aria-label="Send message"
          className="grid h-[30px] w-[30px] place-items-center rounded-md bg-accent text-accent-deep hover:bg-[#d9edbc] disabled:opacity-50"><ArrowUp size={17} aria-hidden="true" /></button>
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
    <div className="mb-3 flex flex-wrap items-center gap-2" aria-label="Suggested prompts">
      <button type="button" disabled={disabled} onClick={() => onSend("/guide")}
        className="inline-flex items-center gap-1.5 rounded-md border border-subtle px-2.5 py-2 text-micro text-ink hover:border-accent hover:text-accent-text disabled:opacity-50">
        <BookOpen size={12} aria-hidden="true" />/guide</button>
      {SUGGESTIONS.slice(0, 4).map((s) => (
        <button key={s} type="button" disabled={disabled} onClick={() => onPick(s)}
          className="max-w-full truncate rounded-md border border-subtle px-2.5 py-2 text-left text-micro text-ink-2 hover:border-accent hover:text-accent-text disabled:opacity-50 sm:max-w-[260px]" title={s}>
          {s} <span className="text-accent-text" aria-hidden="true">↗</span></button>
      ))}
    </div>
  );
}

export function EmptyChat() {
  return (
    <div>
      <AgentLabel />
      <h2 className="mt-5 font-display text-[28px] font-medium leading-[1.3] tracking-[-0.04em]">Tell me what to pay,<br />and to whom.</h2>
      <p className="mt-4 max-w-[62ch] text-sm leading-[1.9] text-ink-2">
        For example: “Create escrow for Lumen PO-104, PHP 120,000, 20% down, delivery by 2026-10-30”. Inside the limits you set,
        a deal you describe in full is created and funded by the agent itself. Anything larger, flagged or filled in by the agent
        comes back to you for a yes. Type <span className="font-mono text-ink">/guide</span> for everything TR8DE can do.
      </p>
      <div className="mt-6 flex gap-3 border-l-2 border-accent bg-gradient-to-r from-[#222c1b80] to-transparent px-4 py-3.5">
        <span className="text-[20px] text-accent-text" aria-hidden="true">↗</span>
        <div><strong className="text-cap font-medium text-accent-text">One request. Every check.</strong>
          <p className="mt-1 text-cap leading-6 text-ink-2">The Coordinator drafts, your words are checked in code, the Checker reviews, the policy decides, and the contract enforces.</p></div>
      </div>
    </div>
  );
}
