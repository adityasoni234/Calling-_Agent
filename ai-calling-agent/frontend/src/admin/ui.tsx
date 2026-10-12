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
    <section className="overflow-hidden rounded-xl border border-ink-200/60 bg-white">
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-ink-200/60 px-4 py-3">
          <div className="min-w-0">
            {title && (
              <h2 className="text-sm font-medium text-ink-900">{title}</h2>
            )}
            {description && (
              <p className="mt-0.5 text-xs leading-relaxed text-ink-400">
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
      ? "text-emerald-700"
      : tone === "bad"
        ? "text-red-700"
        : "text-ink-900";
  return (
    <div className="rounded-xl border border-ink-200/60 bg-white px-4 py-3.5">
      <p className="text-[0.65rem] font-medium uppercase tracking-[0.1em] text-ink-400">
        {label}
      </p>
      <p
        className={`mt-1.5 text-2xl font-semibold tabular-nums leading-none ${colour}`}
      >
        {value}
      </p>
      {sub && <p className="mt-1.5 text-[0.7rem] text-ink-400">{sub}</p>}
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
          <tr className="border-b border-ink-200/60 text-left">
            {headers.map((header, index) => (
              <th
                key={header || index}
                className={`whitespace-nowrap py-2.5 text-[0.65rem] font-medium uppercase tracking-[0.1em] text-ink-400 ${
                  index === 0 ? "pl-4 pr-3" : "px-3"
                }`}
              >
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-200/60">{children}</tbody>
      </table>
    </div>
  );
}

const PILL: Record<string, string> = {
  active: "border-emerald-200 bg-emerald-50 text-emerald-700",
  suspended: "border-red-200 bg-red-50 text-red-700",
  inactive: "border-ink-300/70 bg-ink-100 text-ink-500",
  trial: "border-ink-300/70 bg-ink-100 text-ink-700",
  starter: "border-sky-200 bg-sky-50 text-sky-700",
  growth: "border-violet-200 bg-violet-50 text-violet-700",
  scale: "border-amber-200 bg-amber-50 text-amber-700",
  grant: "border-emerald-200 bg-emerald-50 text-emerald-700",
  purchase: "border-emerald-200 bg-emerald-50 text-emerald-700",
  usage: "border-ink-300/70 bg-ink-100 text-ink-500",
  adjustment: "border-amber-200 bg-amber-50 text-amber-700",
};

export function Pill({ value }: { value: string }) {
  const tone = PILL[value] ?? "border-ink-300/70 bg-ink-100 text-ink-700";
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
  // Separate from `busy`, because they say different things: busy means the
  // request is in flight, disabled means the form is not ready. Folding them
  // together made an incomplete form look like a request that had hung.
  disabled = false,
}: {
  children: ReactNode;
  onClick: () => void;
  tone?: "default" | "primary" | "danger";
  busy?: boolean;
  disabled?: boolean;
}) {
  const style =
    tone === "primary"
      ? "bg-brand-700 text-white hover:bg-ink-50"
      : tone === "danger"
        ? "border border-red-200 text-red-700 hover:bg-red-50"
        : "border border-ink-300/70 text-ink-700 hover:bg-ink-100";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || disabled}
      className={`whitespace-nowrap rounded-md px-2 py-1 text-[0.7rem] font-medium transition-colors disabled:opacity-50 ${style}`}
    >
      {busy ? "…" : children}
    </button>
  );
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-12 text-center">
      <p className="text-sm text-ink-700">{title}</p>
      {hint && (
        <p className="mx-auto mt-1.5 max-w-sm text-xs text-ink-400">{hint}</p>
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
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-ink-200/60 pb-4">
      <div>
        <h1 className="text-lg font-semibold text-ink-900">{title}</h1>
        {description && (
          <p className="mt-1 text-xs text-ink-400">{description}</p>
        )}
      </div>
      {actions}
    </header>
  );
}
