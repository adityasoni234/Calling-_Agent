interface StatCardProps {
  label: string
  value: string
  hint?: string
  pending?: boolean
  /** Draws a rule above the one figure that matters most on the page. */
  accent?: boolean
}

/**
 * A figure, set large, with its label beneath.
 *
 * The previous version boxed and shadowed every number, which made six of them
 * compete for attention. Here the numeral does the work and whitespace does the
 * separating -- the figure is what someone actually came to read.
 */
export function StatCard({ label, value, hint, pending = false, accent = false }: StatCardProps) {
  return (
    <div
      className={`animate-fade-up border-t pt-4 ${
        accent ? 'border-brand-600' : 'border-ink-200/70'
      }`}
    >
      <p className="text-2xs font-medium uppercase tracking-[0.1em] text-ink-400">{label}</p>
      <p
        className={`mt-2.5 font-display text-[2rem] font-normal leading-none tabular-nums ${
          accent ? 'text-brand-700' : 'text-ink-900'
        }`}
      >
        {pending ? <span className="skeleton block h-8 w-20 rounded" /> : value}
      </p>
      {hint && <p className="mt-2 text-xs leading-relaxed text-ink-400">{hint}</p>}
    </div>
  )
}
