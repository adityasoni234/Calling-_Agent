interface StatCardProps {
  label: string
  value: string
  hint?: string
  pending?: boolean
  /** Draws attention to the one metric that matters most on the page. */
  accent?: boolean
}

export function StatCard({ label, value, hint, pending = false, accent = false }: StatCardProps) {
  return (
    <div
      className={`group relative animate-fade-up overflow-hidden rounded-2xl px-5 py-4 shadow-card ring-1 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-lift ${
        accent
          ? 'bg-brand-sheen text-white ring-brand-600/20'
          : 'bg-white text-ink-900 ring-ink-200/70'
      }`}
    >
      {/* A hairline of brand colour ties plain cards back to the palette. */}
      {!accent && (
        <span className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-brand-400/60 to-transparent" />
      )}
      <p
        className={`text-2xs font-semibold uppercase tracking-wider ${
          accent ? 'text-brand-100' : 'text-ink-400'
        }`}
      >
        {label}
      </p>
      <p className="mt-2.5 text-[1.75rem] font-semibold leading-none tabular-nums">
        {pending ? <span className="skeleton block h-7 w-20 rounded-md" /> : value}
      </p>
      {hint && (
        <p className={`mt-2 text-xs ${accent ? 'text-brand-100/90' : 'text-ink-400'}`}>{hint}</p>
      )}
    </div>
  )
}
