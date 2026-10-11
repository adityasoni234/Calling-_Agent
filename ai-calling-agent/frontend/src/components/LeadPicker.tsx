import { useState } from 'react'

import { Badge } from '@/components/ui/Badge'
import { useLeadLists, useLeads } from '@/hooks/api'
import { api } from '@/lib/api'
import type { Lead, Page } from '@/types/api'

/**
 * Choose leads for a campaign.
 *
 * The previous version rendered one page of leads as a plain checkbox list —
 * fine for five, unusable for five hundred. This searches, filters by status,
 * selects a whole page at once, and keeps count of what is selected across
 * pages.
 */
export function LeadPicker({
  selected,
  onChange,
}: {
  selected: string[]
  onChange: (next: string[]) => void
}) {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [sheet, setSheet] = useState('')
  const [page, setPage] = useState(1)
  const [selectingAll, setSelectingAll] = useState(false)
  const { data: sheetData } = useLeadLists()
  const sheets = sheetData ?? []
  const { data, isLoading } = useLeads({
    page,
    search: search || undefined,
    status: status || undefined,
    list_id: sheet || undefined,
  })

  const items = data?.items ?? []
  const pageIds = items.map((lead) => lead.id)
  const allOnPageSelected = pageIds.length > 0 && pageIds.every((id) => selected.includes(id))

  const toggle = (id: string) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id])

  // Pull every matching id, not just the visible page. Pages are 25, so a
  // 163-lead sheet is a handful of requests rather than seven clicks and a
  // scroll each time.
  const selectEverythingMatching = async () => {
    setSelectingAll(true)
    try {
      const ids: string[] = []
      const pages = data?.pages ?? 1
      for (let next = 1; next <= pages; next += 1) {
        const chunk = await api.get<Page<Lead>>(
          `/leads?${new URLSearchParams({
            page: String(next),
            page_size: '100',
            ...(search ? { search } : {}),
            ...(status ? { status } : {}),
            ...(sheet ? { list_id: sheet } : {}),
          })}`,
        )
        ids.push(...chunk.items.map((lead) => lead.id))
        if (next >= chunk.pages) break
      }
      onChange([...new Set([...selected, ...ids])])
    } finally {
      setSelectingAll(false)
    }
  }

  const togglePage = () =>
    onChange(
      allOnPageSelected
        ? selected.filter((id) => !pageIds.includes(id))
        : [...new Set([...selected, ...pageIds])],
    )

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium text-ink-600">
          Leads{' '}
          <span className="font-normal text-ink-400">
            {selected.length > 0
              ? `— ${selected.length} selected`
              : '— none selected yet'}
          </span>
        </p>
        {selected.length > 0 && (
          <button
            type="button"
            onClick={() => onChange([])}
            className="text-2xs font-medium text-brand-600 hover:text-brand-700"
          >
            Clear selection
          </button>
        )}
      </div>

      {sheets.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1">
          <SheetChip label="All leads" selected={!sheet} onClick={() => { setSheet(''); setPage(1) }} />
          {sheets.map((item) => (
            <SheetChip
              key={item.id}
              label={`${item.name} (${item.lead_count})`}
              selected={sheet === item.id}
              onClick={() => {
                setSheet(item.id)
                setPage(1)
              }}
            />
          ))}
        </div>
      )}

      <div className="mt-2 flex gap-2">
        <input
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
          placeholder="Search name, phone, company"
          className="min-w-0 flex-1 rounded-xl border-0 bg-white px-3 py-2 text-sm shadow-card ring-1 ring-inset ring-ink-200 focus:ring-2 focus:ring-brand-500"
        />
        <select
          value={status}
          onChange={(event) => {
            setStatus(event.target.value)
            setPage(1)
          }}
          className="rounded-xl border-0 bg-white px-3 py-2 text-sm shadow-card ring-1 ring-inset ring-ink-200 focus:ring-2 focus:ring-brand-500"
        >
          <option value="">Any status</option>
          {['new', 'contacted', 'interested', 'qualified', 'callback'].map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-2 max-h-64 overflow-y-auto rounded-xl bg-white ring-1 ring-ink-200">
        {isLoading ? (
          <p className="p-4 text-sm text-ink-500">Loading…</p>
        ) : items.length === 0 ? (
          <p className="p-4 text-sm text-ink-500">
            No leads match. Add leads first, or widen the filter.
          </p>
        ) : (
          <>
            <div className="flex items-center justify-between gap-3 border-b border-ink-100 bg-ink-50/60 px-3 py-2">
              <label className="flex cursor-pointer items-center gap-3 text-xs font-medium text-ink-600">
                <input
                  type="checkbox"
                  checked={allOnPageSelected}
                  onChange={togglePage}
                  className="rounded border-ink-300 text-brand-600 focus:ring-brand-500"
                />
                Select all {items.length} on this page
              </label>
              {/* Ticking 163 boxes across nine pages is not a workflow. */}
              {(data?.pages ?? 1) > 1 && (
                <button
                  type="button"
                  disabled={selectingAll}
                  onClick={selectEverythingMatching}
                  className="text-2xs font-medium text-brand-600 hover:text-brand-700 disabled:opacity-50"
                >
                  {selectingAll ? 'Selecting…' : `Select all ${data?.total} matching`}
                </button>
              )}
            </div>
            {items.map((lead) => (
              <label
                key={lead.id}
                className="flex cursor-pointer items-center gap-3 border-b border-ink-100 px-3 py-2 text-sm last:border-0 hover:bg-ink-50"
              >
                <input
                  type="checkbox"
                  checked={selected.includes(lead.id)}
                  onChange={() => toggle(lead.id)}
                  className="rounded border-ink-300 text-brand-600 focus:ring-brand-500"
                />
                <span className="min-w-0 flex-1 truncate font-medium text-ink-800">{lead.name}</span>
                <span className="tabular-nums text-ink-500">{lead.phone_number}</span>
                <Badge value={lead.status} />
              </label>
            ))}
          </>
        )}
      </div>

      {(data?.pages ?? 1) > 1 && (
        <div className="mt-2 flex items-center justify-between text-2xs text-ink-500">
          <span>
            Page {data?.page} of {data?.pages} · {data?.total} leads
          </span>
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
              className="rounded-lg px-2 py-1 ring-1 ring-ink-200 disabled:opacity-40"
            >
              Prev
            </button>
            <button
              type="button"
              disabled={page >= (data?.pages ?? 1)}
              onClick={() => setPage(page + 1)}
              className="rounded-lg px-2 py-1 ring-1 ring-ink-200 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function SheetChip({
  label,
  selected,
  onClick,
}: {
  label: string
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      className={`max-w-48 truncate rounded-lg px-2.5 py-1 text-2xs font-medium transition-colors ${
        selected
          ? 'bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200'
          : 'text-ink-500 hover:bg-ink-100 hover:text-ink-800'
      }`}
    >
      {label}
    </button>
  )
}
