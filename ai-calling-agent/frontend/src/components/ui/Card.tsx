import type { ReactNode } from 'react'

interface CardProps {
  title?: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
  /** Removes the body padding — for tables that should reach the card edge. */
  flush?: boolean
}

export function Card({
  title,
  description,
  actions,
  children,
  className = '',
  flush = false,
}: CardProps) {
  return (
    <section
      className={`animate-fade-up overflow-hidden rounded-2xl bg-white shadow-card ring-1 ring-ink-200/70 transition-shadow duration-200 hover:shadow-lift ${className}`}
    >
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-ink-100 px-5 py-4">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink-900">{title}</h2>}
            {description && <p className="mt-1 text-xs leading-relaxed text-ink-500">{description}</p>}
          </div>
          {actions && <div className="shrink-0">{actions}</div>}
        </header>
      )}
      <div className={flush ? '' : 'px-5 py-4'}>{children}</div>
    </section>
  )
}
