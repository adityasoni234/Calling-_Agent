import { Card } from '@/components/ui/Card'

interface PhasePlaceholderProps {
  title: string
  phase: string
  summary: string
  scope: string[]
}

/**
 * Explicit "not built yet" panel. Every module the roadmap promises has a route
 * from day one, and each one states which phase delivers it -- so the shell is
 * honest about what exists instead of showing invented data.
 */
export function PhasePlaceholder({ title, phase, summary, scope }: PhasePlaceholderProps) {
  return (
    <div className="mx-auto max-w-3xl">
      <Card title={title} description={summary}>
        <p className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
          Ships in {phase}
        </p>
        <ul className="mt-4 space-y-2 text-sm text-slate-600">
          {scope.map((item) => (
            <li key={item} className="flex gap-2.5">
              <span aria-hidden className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-300" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  )
}
