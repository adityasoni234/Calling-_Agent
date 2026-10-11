import type { ReactNode } from "react";

/**
 * Admin primitives.
 *
 * Separate from the customer design system on purpose: this is an internal
 * tool, and it should never be mistaken for the product at a glance.
 */

export function Panel({
  title,
  description,
  actions,
  children,
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900">
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-slate-800 px-4 py-3">
          <div className="min-w-0">
            {title && (
              <h2 className="text-sm font-medium text-slate-100">{title}</h2>
            )}
            {description && (
              <p className="mt-0.5 text-xs leading-relaxed text-slate-500">
                {description}
              </p>
            )}
          </div>
          {actions && <div className="shrink-0">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Metric({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "good" | "bad";
}) {
  const colour =
    tone === "good"
      ? "text-emerald-400"
      : tone === "bad"
        ? "text-red-400"
        : "text-slate-100";
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 px-4 py-3.5">
      <p className="text-[0.65rem] font-medium uppercase tracking-[0.1em] text-slate-500">
        {label}
      </p>
      <p
        className={`mt-1.5 text-2xl font-semibold tabular-nums leading-none ${colour}`}
      >
        {value}
      </p>
      {sub && <p className="mt-1.5 text-[0.7rem] text-slate-500">{sub}</p>}
    </div>
  );
}

export function Grid({
  headers,
  children,
}: {
  headers: string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-[0.8rem]">
        <thead>
          <tr className="border-b border-slate-800 text-left">
            {headers.map((header, index) => (
              <th
                key={header || index}
                className={`whitespace-nowrap py-2.5 text-[0.65rem] font-medium uppercase tracking-[0.1em] text-slate-500 ${
                  index === 0 ? "pl-4 pr-3" : "px-3"
                }`}
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/80">{children}</tbody>
      </table>
    </div>
  );
}

const PILL: Record<string, string> = {
  active: "border-emerald-900/60 bg-emerald-950/50 text-emerald-400",
  suspended: "border-red-900/60 bg-red-950/50 text-red-400",
  inactive: "border-slate-700 bg-slate-800 text-slate-400",
  trial: "border-slate-700 bg-slate-800 text-slate-300",
  starter: "border-sky-900/60 bg-sky-950/50 text-sky-400",
  growth: "border-violet-900/60 bg-violet-950/50 text-violet-400",
  scale: "border-amber-900/60 bg-amber-950/50 text-amber-400",
  grant: "border-emerald-900/60 bg-emerald-950/50 text-emerald-400",
  purchase: "border-emerald-900/60 bg-emerald-950/50 text-emerald-400",
  usage: "border-slate-700 bg-slate-800 text-slate-400",
  adjustment: "border-amber-900/60 bg-amber-950/50 text-amber-400",
};

export function Pill({ value }: { value: string }) {
  const tone = PILL[value] ?? "border-slate-700 bg-slate-800 text-slate-300";
  return (
    <span
      className={`inline-flex whitespace-nowrap rounded border px-1.5 py-0.5 text-[0.65rem] font-medium ${tone}`}
    >
      {value.replace(/[._]/g, " ")}
    </span>
  );
}

export function Action({
  children,
  onClick,
  tone = "default",
  busy = false,
}: {
  children: ReactNode;
  onClick: () => void;
  tone?: "default" | "primary" | "danger";
  busy?: boolean;
}) {
  const style =
    tone === "primary"
      ? "bg-slate-100 text-slate-950 hover:bg-white"
      : tone === "danger"
        ? "border border-red-900/60 text-red-400 hover:bg-red-950/40"
        : "border border-slate-700 text-slate-300 hover:bg-slate-800";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className={`whitespace-nowrap rounded-md px-2 py-1 text-[0.7rem] font-medium transition-colors disabled:opacity-50 ${style}`}
    >
      {busy ? "…" : children}
    </button>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-12 text-center">
      <p className="text-sm text-slate-300">{title}</p>
      {hint && (
        <p className="mx-auto mt-1.5 max-w-sm text-xs text-slate-500">{hint}</p>
      )}
    </div>
  );
}

export function PageTitle({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-slate-800 pb-4">
      <div>
        <h1 className="text-lg font-semibold text-slate-100">{title}</h1>
        {description && (
          <p className="mt-1 text-xs text-slate-500">{description}</p>
        )}
      </div>
      {actions}
    </header>
  );
}
