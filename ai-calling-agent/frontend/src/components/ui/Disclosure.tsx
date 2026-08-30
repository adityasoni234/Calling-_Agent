import { type ReactNode, useState } from 'react'

interface DisclosureProps {
  title: string
  description?: string
  children: ReactNode
  defaultOpen?: boolean
  /** Shown collapsed, so you can tell whether it needs attention. */
  summary?: string
}

/**
 * A collapsible section.
 *
 * Agent configuration has around twenty fields. Showing all of them at once
 * makes a simple job look hard, so the ones with sensible defaults start
 * closed with a one-line summary of what they are set to.
 */
export function Disclosure({
  title,
  description,
  children,
  defaultOpen = false,
  summary,
}: DisclosureProps) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="overflow-hidden rounded-xl ring-1 ring-ink-200">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-3 bg-ink-50/70 px-4 py-3 text-left transition-colors hover:bg-ink-100/70"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          className={`h-3.5 w-3.5 shrink-0 text-ink-400 transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
          aria-hidden
        >
          <path d="M9 6l6 6-6 6" />
        </svg>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-ink-800">{title}</span>
          {description && <span className="mt-0.5 block text-xs text-ink-500">{description}</span>}
        </span>
        {!open && summary && (
          <span className="hidden shrink-0 text-2xs text-ink-400 sm:block">{summary}</span>
        )}
      </button>
      {open && <div className="space-y-4 border-t border-ink-100 bg-white px-4 py-4">{children}</div>}
    </div>
  )
}
