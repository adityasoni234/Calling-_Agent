import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Inputs";
import { StatCard } from "@/components/ui/StatCard";
import { EmptyState, Pager, Table } from "@/components/ui/Table";
import { useLeadCount, useLeads } from "@/hooks/api";
import type { LeadQuery } from "@/hooks/api";
import { downloadCsv } from "@/lib/csv";
import { formatDateTime } from "@/lib/format";
import { CallDialog } from "@/pages/LeadsPage";
import type { Lead } from "@/types/api";

/**
 * The hand-off list. Leads sit here once a call proved they are worth a
 * human's time, so the ordering is by score — never by when they were added.
 */
const SEGMENTS = [
  {
    key: "qualified",
    label: "Qualified",
    statuses: "qualified,converted",
    blurb:
      "Passed the qualification questions on a call. Ready for a human to close.",
  },
  {
    key: "warm",
    label: "Warm",
    statuses: "interested,callback",
    blurb: "Interested but not qualified yet — worth another call.",
  },
  {
    key: "won",
    label: "Converted",
    statuses: "converted",
    blurb: "Closed. Kept here so you can see what a good lead looked like.",
  },
] as const;

type SegmentKey = (typeof SEGMENTS)[number]["key"];

function ScoreBar({ score }: { score: number }) {
  // Colour carries the same meaning as the number, for a fast scan down the column.
  const tone =
    score >= 70
      ? "bg-emerald-500"
      : score >= 40
        ? "bg-amber-500"
        : "bg-ink-300";
  return (
    <div className="flex items-center gap-2">
      <span className="w-7 text-right text-xs font-semibold tabular-nums text-ink-800">
        {score}
      </span>
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-ink-100">
        <span
          className={`block h-full rounded-full ${tone}`}
          style={{ width: `${score}%` }}
        />
      </span>
    </div>
  );
}

export function QualifiedPage() {
  const [segment, setSegment] = useState<SegmentKey>("qualified");
  const [page, setPage] = useState(1);
  const [minScore, setMinScore] = useState(0);
  const [sort, setSort] = useState<NonNullable<LeadQuery["sort"]>>("score");
  const [callFor, setCallFor] = useState<Lead | null>(null);

  const active = SEGMENTS.find((item) => item.key === segment) ?? SEGMENTS[0];
  const { data, isLoading } = useLeads({
    page,
    statuses: active.statuses,
    min_score: minScore || undefined,
    sort,
  });
  const qualifiedCount = useLeadCount("qualified,converted");
  const warmCount = useLeadCount("interested,callback");
  const wonCount = useLeadCount("converted");

  const counts: Record<SegmentKey, number | undefined> = {
    qualified: qualifiedCount.data,
    warm: warmCount.data,
    won: wonCount.data,
  };

  const rows = data?.items ?? [];
  const averageScore = rows.length
    ? Math.round(
        rows.reduce((total, lead) => total + lead.lead_score, 0) / rows.length,
      )
    : 0;

  const exportCsv = () => {
    const header = [
      "name",
      "phone",
      "email",
      "company",
      "status",
      "score",
      "interest",
      "calls",
      "last_called",
    ];
    const body = rows.map((lead) => [
      lead.name,
      lead.phone_number,
      lead.email ?? "",
      lead.company_name ?? "",
      lead.status,
      String(lead.lead_score),
      lead.interest_level,
      String(lead.call_count),
      lead.last_called_at ?? "",
    ]);
    const escape = (value: string) =>
      /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
    downloadCsv(
      `${active.key}-leads.csv`,
      [header, ...body].map((row) => row.map(escape).join(",")).join("\n"),
    );
  };

  const switchSegment = (key: SegmentKey) => {
    setSegment(key);
    setPage(1);
  };

  return (
    <div className="space-y-5">
      <PageHeader
        title="Qualified Leads"
        description="Everyone your agents judged worth following up, best first."
        actions={
          <Button
            variant="secondary"
            onClick={exportCsv}
            disabled={rows.length === 0}
          >
            Export this view
          </Button>
        }
      />

      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard
          label="Qualified"
          value={String(qualifiedCount.data ?? 0)}
          pending={qualifiedCount.isLoading}
          hint="Ready to hand to a closer"
          accent
        />
        <StatCard
          label="Warm"
          value={String(warmCount.data ?? 0)}
          pending={warmCount.isLoading}
          hint="Interested, needs another call"
        />
        <StatCard
          label="Average score"
          value={rows.length ? String(averageScore) : "—"}
          pending={isLoading}
          hint="Across the leads shown below"
        />
      </div>

      <Card
        flush
        title={active.label}
        description={active.blurb}
        actions={
          <div className="flex flex-wrap items-end gap-2">
            <Select
              label="Minimum score"
              value={String(minScore)}
              onChange={(event) => {
                setMinScore(Number(event.target.value));
                setPage(1);
              }}
            >
              <option value="0">Any score</option>
              <option value="40">40 and above</option>
              <option value="60">60 and above</option>
              <option value="80">80 and above</option>
            </Select>
            <Select
              label="Sort by"
              value={sort}
              onChange={(event) =>
                setSort(event.target.value as NonNullable<LeadQuery["sort"]>)
              }
            >
              <option value="score">Highest score</option>
              <option value="last_called">Recently called</option>
              <option value="name">Name</option>
            </Select>
          </div>
        }
      >
        <div className="flex gap-1 border-b border-ink-100 px-5 py-3">
          {SEGMENTS.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => switchSegment(item.key)}
              className={`rounded-xl px-3 py-1.5 text-xs font-medium transition-colors ${
                item.key === segment
                  ? "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200"
                  : "text-ink-500 hover:bg-ink-100 hover:text-ink-800"
              }`}
            >
              {item.label}
              {counts[item.key] !== undefined && (
                <span className="ml-1.5 tabular-nums opacity-70">
                  {counts[item.key]}
                </span>
              )}
            </button>
          ))}
        </div>

        {isLoading ? (
          <div className="space-y-2 px-5 py-5">
            {[0, 1, 2, 3].map((row) => (
              <div key={row} className="skeleton h-9 rounded-xl" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            title={`No ${active.label.toLowerCase()} leads yet`}
            hint={
              minScore > 0
                ? "Try lowering the minimum score — the filter may be hiding everyone."
                : "Leads land here automatically once a call scores them. Run a campaign to fill it."
            }
          />
        ) : (
          <>
            {/* Table bleeds with -mx-5, so it needs a px-5 parent to cancel against. */}
            <div className="px-5">
              <Table
                headers={[
                  "Lead",
                  "Score",
                  "Status",
                  "Interest",
                  "Calls",
                  "Last called",
                  "",
                ]}
              >
                {rows.map((lead) => (
                  <tr
                    key={lead.id}
                    className="transition-colors hover:bg-ink-50/60"
                  >
                    <td className="py-3 pl-5 pr-3">
                      <p className="font-medium text-ink-900">{lead.name}</p>
                      <p className="text-xs tabular-nums text-ink-500">
                        {lead.phone_number}
                        {lead.company_name && (
                          <span className="ml-2 text-ink-400">
                            {lead.company_name}
                          </span>
                        )}
                      </p>
                    </td>
                    <td className="px-3 py-3">
                      <ScoreBar score={lead.lead_score} />
                    </td>
                    <td className="px-3 py-3">
                      <Badge value={lead.status} />
                    </td>
                    <td className="px-3 py-3">
                      <Badge value={lead.interest_level} />
                    </td>
                    <td className="px-3 py-3 tabular-nums text-ink-600">
                      {lead.call_count}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-xs text-ink-500">
                      {formatDateTime(lead.last_called_at)}
                    </td>
                    <td className="px-3 py-3 text-right">
                      <div className="flex justify-end gap-1.5">
                        <Link
                          to={`/calls?search=${encodeURIComponent(lead.phone_number)}`}
                          className="rounded-xl px-2.5 py-1.5 text-xs font-medium text-ink-500 transition-colors hover:bg-ink-100 hover:text-ink-800"
                        >
                          Calls
                        </Link>
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => setCallFor(lead)}
                        >
                          Call
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </Table>
            </div>
            <div className="px-5 pb-4">
              <Pager
                page={data?.page ?? 1}
                pages={data?.pages ?? 1}
                total={data?.total ?? 0}
                onChange={setPage}
              />
            </div>
          </>
        )}
      </Card>

      {callFor && (
        <CallDialog lead={callFor} onClose={() => setCallFor(null)} />
      )}
    </div>
  );
}
