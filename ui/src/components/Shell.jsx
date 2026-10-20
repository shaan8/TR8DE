import { useState } from "react";
import clsx from "clsx";
import { Handshake, LayoutList, LogOut, Menu, Sparkles, Store, X } from "lucide-react";
import { logout } from "../Login.jsx";

const NAV = [
  ["", "Agent workspace", Sparkles],
  ["payments", "Payments", LayoutList],
  ["negotiate", "Negotiations", Handshake],
  ["suppliers", "Suppliers", Store],
];

export const go = (view, extra = {}) => {
  const p = new URLSearchParams();
  if (view) p.set("view", view);
  for (const [k, v] of Object.entries(extra)) if (v) p.set(k, v);
  window.location.search = p;
};

export function Brand({ as: As = "h1", className }) {
  return (
    <As aria-label="TR8DE" className={clsx("flex items-center font-display text-[25px] font-extrabold tracking-[-0.06em] text-ink", className)}>
      <span aria-hidden="true" className="mr-2.5 inline-block -rotate-[7deg] text-[28px] font-bold text-accent">↗</span>
      TR<span className="text-accent">8</span>DE
    </As>
  );
}

/** Left rail: brand, workspace nav, quick prompts, connection and owner. `owner` false is the supplier's own page. */
function Sidebar({ active, prompts, onPrompt, status, owner, open, onClose, counts = {} }) {
  return (
    <aside aria-label="Sidebar" className={clsx(
      "z-20 w-[236px] shrink-0 flex-col border-r border-line bg-surface px-4 pb-4 pt-7",
      open ? "fixed inset-y-0 left-0 flex shadow-[15px_0_50px_#0008]" : "hidden md:flex")}>
      <div className="mb-8 flex items-center justify-between px-3">
        <Brand />
        <span className="rounded border border-subtle px-1.5 py-0.5 text-[10px] tracking-widest text-ink-2">BETA</span>
        {open && <button onClick={onClose} aria-label="Close menu" className="ml-2 text-ink-2 md:hidden"><X size={18} /></button>}
      </div>
      {owner ? (
        <nav aria-label="Workspace" className="grid gap-1">
          {NAV.map(([v, label, Icon]) => (
            <button key={label} onClick={() => go(v)} aria-current={active === v ? "page" : undefined}
              className={clsx("flex items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm",
                active === v ? "bg-accent-soft text-accent-text" : "text-ink-2 hover:text-accent-text")}>
              <Icon size={17} aria-hidden="true" />{label}
              {counts[v] ? <span className="ml-auto rounded bg-subtle px-1.5 text-micro text-ink">{counts[v]}</span> : null}
            </button>
          ))}
        </nav>
      ) : (
        <nav aria-label="Workspace" className="grid gap-1">
          <span className="flex items-center gap-3 rounded-md bg-accent-soft px-3 py-2.5 text-sm text-accent-text"><Store size={17} aria-hidden="true" />Supplier console</span>
        </nav>
      )}
      {prompts?.length > 0 && (
        <div className="relative mt-8 min-h-0 overflow-y-auto">
          <p className="px-3 text-micro font-semibold tracking-[0.12em] text-ink-2">QUICK PROMPTS</p>
          <ul className="mt-2">
            {prompts.map((p) => (
              <li key={p}><button onClick={() => { onPrompt(p); onClose?.(); }} title={p}
                className="w-full truncate rounded px-3 py-2 text-left text-cap text-ink-2 hover:bg-raised hover:text-ink">{p}</button></li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-auto pt-4">
        <p className="mb-4 flex items-start gap-2 border-b border-line px-3 pb-4 text-micro text-ink-2">
          <span className="mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-hidden="true" />{status}
        </p>
        {owner && (
          <button onClick={logout} className="flex w-full items-center gap-3 px-2 text-left text-sm text-ink-2 hover:text-accent-text">
            <span className="grid h-8 w-8 place-items-center rounded-full bg-subtle text-cap text-ink" aria-hidden="true">O</span>
            <span>Owner<span className="block text-micro text-ink-2">Sign out</span></span>
            <LogOut size={15} className="ml-auto" aria-hidden="true" />
          </button>
        )}
      </div>
    </aside>
  );
}

/** The design's three-pane workspace: sidebar, the main column, and an optional right canvas. */
export function Shell({ active, crumb, actions, canvas, children, prompts, onPrompt, status, owner = true, counts }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-[100dvh] md:h-[100dvh]">
      <Sidebar active={active} prompts={prompts} onPrompt={onPrompt} status={status} owner={owner}
        open={open} onClose={() => setOpen(false)} counts={counts} />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex min-h-[64px] shrink-0 flex-wrap items-center gap-3 border-b border-line px-4 py-2 md:px-7">
          <button className="md:hidden" onClick={() => setOpen(true)} aria-label="Open menu"><Menu size={20} /></button>
          {!open && <Brand className="text-[21px] md:hidden" />}
          <p className="hidden items-center gap-3 text-cap text-ink-2 md:flex">Workspace <span aria-hidden="true" className="text-subtle">/</span>
            <strong className="font-medium text-ink">{crumb}</strong></p>
          <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
          {canvas && (
            <aside aria-label="Treasury overview" className="relative min-w-0 border-t border-line bg-surface lg:w-[41%] lg:min-w-[340px] lg:max-w-[560px] lg:overflow-y-auto lg:border-l lg:border-t-0">
              {canvas}
            </aside>
          )}
        </div>
      </div>
    </div>
  );
}
