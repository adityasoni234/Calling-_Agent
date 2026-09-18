import { useState } from 'react'

import { useDeleteLeadList, useRenameLeadList } from '@/hooks/api'
import type { LeadList } from '@/types/api'

interface SheetTabsProps {
  sheets: LeadList[]
  /** null selects "All leads". */
  active: string | null
  total?: number
  onSelect: (id: string | null) => void
}

/**
 * One tab per uploaded sheet, plus "All leads".
 *
 * People think of their contacts by the file they arrived in, so the upload
 * keeps its identity here instead of dissolving into one undifferentiated
 * pile the moment it lands.
 */
export function SheetTabs({ sheets, active, total, onSelect }: SheetTabsProps) {
  const [menuFor, setMenuFor] = useState<string | null>(null)
  const rename = useRenameLeadList()
  const remove = useDeleteLeadList()

  const current = sheets.find((sheet) => sheet.id === active)

  return (
    <div className="border-b border-ink-100 bg-ink-50/40">
      <div className="flex items-end gap-1 overflow-x-auto px-3 pt-2">
        <Tab label="All leads" count={total} selected={active === null} onClick={() => onSelect(null)} />
        {sheets.map((sheet) => (
          <Tab
            key={sheet.id}
            label={sheet.name}
            count={sheet.lead_count}
            selected={sheet.id === active}
            onClick={() => onSelect(sheet.id)}
          />
        ))}
      </div>

      {current && (
        <div className="flex flex-wrap items-center gap-3 px-5 py-2 text-xs text-ink-500">
          <span>
            From <span className="font-medium text-ink-700">{current.source_filename ?? 'an upload'}</span>
            {current.skipped_count > 0 && ` · ${current.skipped_count} row(s) skipped on import`}
          </span>
          <button
            type="button"
            onClick={() => {
              const name = prompt('Rename this sheet', current.name)?.trim()
              if (name && name !== current.name) rename.mutate({ id: current.id, name })
              setMenuFor(null)
            }}
            className="rounded-lg px-2 py-1 font-medium text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-800"
          >
            Rename
          </button>
          <button
            type="button"
            onClick={() => {
              // Say plainly that the contacts survive -- otherwise nobody dares
              // click it, and the tabs become permanent clutter.
              if (
                confirm(
                  `Remove the "${current.name}" tab?\n\nThe ${current.lead_count} lead(s) on it are kept and stay under All leads.`,
                )
              ) {
                remove.mutate(current.id)
                onSelect(null)
              }
              setMenuFor(menuFor)
            }}
            className="rounded-lg px-2 py-1 font-medium text-ink-500 transition-colors hover:bg-red-50 hover:text-red-700"
          >
            Remove tab
          </button>
        </div>
      )}
    </div>
  )
}

function Tab({
  label,
  count,
  selected,
  onClick,
}: {
  label: string
  count?: number
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={`-mb-px max-w-52 shrink-0 truncate rounded-t-xl border-b-2 px-3.5 py-2 text-xs font-medium transition-colors ${
        selected
          ? 'border-brand-600 bg-white text-brand-700'
          : 'border-transparent text-ink-500 hover:bg-white/70 hover:text-ink-800'
      }`}
    >
      {label}
      {count !== undefined && <span className="ml-1.5 tabular-nums opacity-60">{count}</span>}
    </button>
  )
}
