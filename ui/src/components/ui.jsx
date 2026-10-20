import clsx from "clsx";

const TONES = {
  ok: "border-ok/50 text-ok",
  warn: "border-warn/50 text-warn",
  bad: "border-bad/60 text-bad",
  accent: "border-accent/50 text-accent-text",
  muted: "border-subtle text-ink-2",
};

/** Status chip: always carries its word, the colour only repeats it. */
export function Chip({ tone = "muted", icon: Icon, children, className, wrap }) {
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-micro font-medium", wrap ? "text-left" : "whitespace-nowrap", TONES[tone], className)}>
      {Icon && <Icon size={12} aria-hidden="true" />}
      {children}
    </span>
  );
}

export function Panel({ title, action, children, className, highlight, id, as: As = "section" }) {
  return (
    <As id={id} aria-label={typeof title === "string" ? title : undefined}
      className={clsx("rounded-lg border border-line bg-surface p-4", highlight && "ring-2 ring-warn", className)}>
      {title && (
        <div className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-micro font-semibold uppercase tracking-[0.12em] text-ink-2">{title}</h2>
          {action}
        </div>
      )}
      {children}
    </As>
  );
}

export function Card({ tone, children, className, ...rest }) {
  const edge = { ok: "border-ok/40", warn: "border-warn/45", bad: "border-bad/50", accent: "border-accent/40" }[tone] || "border-subtle";
  return (
    <div className={clsx("min-w-0 rounded-lg border bg-raised p-4 sm:p-5", edge, className)} {...rest}>
      {children}
    </div>
  );
}

export function Button({ variant = "primary", className, ...rest }) {
  return (
    <button
      className={clsx(
        "inline-flex min-h-[38px] items-center justify-center gap-2 rounded-md px-4 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50",
        variant === "primary" && "bg-accent text-accent-deep hover:bg-[#d9edbc]",
        variant === "ghost" && "border border-subtle text-ink hover:border-accent hover:text-accent-text",
        className,
      )}
      {...rest}
    />
  );
}

export function Row({ label, children, mono }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 py-1.5 sm:grid-cols-[150px_minmax(0,1fr)] sm:gap-3">
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className={clsx("min-w-0 text-sm text-ink [overflow-wrap:anywhere]", mono && "font-mono")}>{children}</dd>
    </div>
  );
}

/** Tiny markdown: **bold**, `code`, paragraphs, "- " and "1. " lists. Agent text only, never HTML. */
export function Prose({ text }) {
  if (!text) return null;
  const inline = (s, k) =>
    s.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((p, i) =>
      p.startsWith("**") ? <strong key={`${k}-${i}`} className="font-semibold">{p.slice(2, -2)}</strong>
      : p.startsWith("`") ? <code key={`${k}-${i}`} className="rounded bg-canvas px-1 font-mono text-[0.92em]">{p.slice(1, -1)}</code>
      : p);
  const lines = text.replace(/```[a-z]*\n?([\s\S]*?)\n?```/g, "`$1`").split("\n").map((l) => l.replace(/\s+$/, ""));
  const blocks = [];
  for (const l of lines) {
    const kind = /^\s*\d+\.\s/.test(l) ? "ol" : /^\s{0,1}-\s/.test(l) ? "ul" : /^\s+-\s/.test(l) ? "sub" : l ? "p" : "gap";
    const last = blocks[blocks.length - 1];
    if (kind === "sub" && last && last.kind !== "p") last.items[last.items.length - 1].subs.push(l.replace(/^\s+-\s/, ""));
    else if (kind === "gap") blocks.push({ kind: "gap" });
    else if (last && last.kind === kind) last.items.push({ t: l, subs: [] });
    else blocks.push({ kind: kind === "sub" ? "ul" : kind, items: [{ t: l, subs: [] }] });
  }
  const strip = (t) => t.replace(/^\s*(-|\d+\.)\s/, "");
  return (
    <div className="space-y-2 text-base leading-[1.8] text-ink/90">
      {blocks.filter((b) => b.kind !== "gap").map((b, i) => {
        if (b.kind === "p") return <p key={i}>{b.items.map((it, j) => <span key={j}>{inline(it.t, j)}{j < b.items.length - 1 && <br />}</span>)}</p>;
        const L = b.kind === "ol" ? "ol" : "ul";
        return (
          <L key={i} className={`${L === "ol" ? "list-decimal" : "list-disc"} space-y-1 pl-6`}>
            {b.items.map((it, j) => (
              <li key={j}>{inline(strip(it.t), j)}
                {it.subs.length > 0 && <ul className="list-[circle] pl-5 text-sm text-ink-2">{it.subs.map((s, k) => <li key={k}>{inline(s, k)}</li>)}</ul>}
              </li>))}
          </L>
        );
      })}
    </div>
  );
}
