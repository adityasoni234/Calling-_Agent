import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  /** One line saying what this screen is for. Every page has one. */
  description?: string
  actions?: ReactNode
}

/**
 * The same header on every screen.
 *
 * Each page had grown its own heading markup, so titles sat at different sizes
 * and some had no description at all — which left a new user guessing what a
 * screen was even for.
 */
export function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 border-b border-ink-200/70 pb-5">
      <div className="min-w-0">
        <h1 className="text-[1.75rem] leading-tight text-ink-900">{title}</h1>
        {description && (
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-500">{description}</p>
        )}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </header>
  )
}
