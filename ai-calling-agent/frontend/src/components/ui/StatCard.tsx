interface StatCardProps {
  label: string
  value: string
  hint?: string
  pending?: boolean
}

export function StatCard({ label, value, hint, pending = false }: StatCardProps) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">
        {pending ? <span className="inline-block h-7 w-16 animate-pulse rounded bg-slate-100" /> : value}
      </p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}
