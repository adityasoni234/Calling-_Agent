import type { ReactNode } from "react";

export function Table({
  headers,
  children,
}: {
  headers: string[];
  children: ReactNode;
}) {
  return (
    <div className="-mx-5 overflow-x-auto">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="border-y border-ink-200/70 text-left">
            {headers.map((header, index) => (
              <th
                key={header || index}
                className={`whitespace-nowrap py-3 text-2xs font-medium uppercase tracking-[0.1em] text-ink-400 ${
                  index === 0 ? "pl-5 pr-3" : "px-3"
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

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  /** Where to go next. An empty screen with no way forward is a dead end. */
  action?: ReactNode;
}) {
  return (
    <div className="py-16 text-center">
      <div className="mx-auto mb-4 grid h-11 w-11 place-items-center rounded-2xl bg-ink-100 text-ink-400">
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          className="h-5 w-5"
          aria-hidden
        >
          <path d="M4 7h16M4 12h10M4 17h7" />
        </svg>
      </div>
      <p className="text-sm font-medium text-ink-800">{title}</p>
      {hint && (
        <p className="mx-auto mt-1.5 max-w-sm text-xs leading-relaxed text-ink-500">
          {hint}
        </p>
      )}
      {action && <div className="mt-4 flex justify-center gap-2">{action}</div>}
    </div>
  );
}

export function Pager({
  page,
  pages,
  total,
  onChange,
}: {
  page: number;
  pages: number;
  total: number;
  onChange: (page: number) => void;
}) {
  if (total === 0) return null;
  return (
    <div className="flex items-center justify-between pt-4 text-xs text-ink-500">
      <span>
        Page {page} of {Math.max(pages, 1)} ·{" "}
        <span className="tabular-nums">{total}</span> total
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => onChange(page - 1)}
          className="rounded-xl bg-white px-2.5 py-1.5 font-medium shadow-card ring-1 ring-ink-200 transition-colors hover:bg-ink-50 disabled:opacity-40 disabled:hover:bg-white"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={page >= pages}
          onClick={() => onChange(page + 1)}
          className="rounded-xl bg-white px-2.5 py-1.5 font-medium shadow-card ring-1 ring-ink-200 transition-colors hover:bg-ink-50 disabled:opacity-40 disabled:hover:bg-white"
        >
          Next
        </button>
      </div>
    </div>
  );
}
