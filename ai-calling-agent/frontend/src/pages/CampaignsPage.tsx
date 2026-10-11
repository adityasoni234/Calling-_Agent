import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Inputs";
import { Modal } from "@/components/ui/Modal";
import { EmptyState, Pager, Table } from "@/components/ui/Table";
import { LeadPicker } from "@/components/LeadPicker";
import { StatCard } from "@/components/ui/StatCard";
import {
  useAgents,
  useCampaign,
  useCampaignControl,
  useAddSheetToCampaign,
  useCampaignLeads,
  useImportCampaignLeads,
  useLeadLists,
  useCampaigns,
  useCreateCampaign,
  useLead,
} from "@/hooks/api";
import { ApiError, NetworkError } from "@/lib/api";
import { downloadCsv, leadTemplateCsv } from "@/lib/csv";
import { formatCurrency, formatDateTime } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";
import type { CampaignImportResult, DispatchResult } from "@/types/api";

export function CampaignsPage() {
  const { data, isLoading } = useCampaigns();
  const [creating, setCreating] = useState(false);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Campaigns"
        description="Dial a whole list automatically, at a pace and budget you control."
        actions={
          <Button onClick={() => setCreating(true)}>New campaign</Button>
        }
      />

      <Card>
        {isLoading ? (
          <p className="py-8 text-center text-sm text-ink-500">Loading…</p>
        ) : !data?.items.length ? (
          <EmptyState
            title="No campaigns yet"
            hint="A campaign dials a list of leads with an agent, inside calling hours you set, a few at a time. You need at least one agent and some leads first."
            action={
              <>
                <Button onClick={() => setCreating(true)}>New campaign</Button>
                <Link
                  to="/agents"
                  className="rounded-xl bg-white px-2.5 py-1.5 text-xs font-medium text-ink-700 shadow-card ring-1 ring-inset ring-ink-200 transition-colors hover:bg-ink-50"
                >
                  Create an agent
                </Link>
                <Link
                  to="/leads"
                  className="rounded-xl bg-white px-2.5 py-1.5 text-xs font-medium text-ink-700 shadow-card ring-1 ring-inset ring-ink-200 transition-colors hover:bg-ink-50"
                >
                  Import leads
                </Link>
              </>
            }
          />
        ) : (
          <Table
            headers={[
              "Name",
              "Status",
              "Calling hours",
              "Concurrency",
              "Retries",
              "",
            ]}
          >
            {data.items.map((campaign) => (
              <tr key={campaign.id} className="hover:bg-ink-50">
                <td className="px-3 py-2.5 font-medium text-ink-900">
                  <Link
                    to={`/campaigns/${campaign.id}`}
                    className="hover:text-brand-700"
                  >
                    {campaign.name}
                  </Link>
                </td>
                <td className="px-3 py-2.5">
                  <Badge value={campaign.status} />
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">
                  {campaign.calling_hours_start.slice(0, 5)}–
                  {campaign.calling_hours_end.slice(0, 5)}
                  <span className="ml-1 text-xs text-ink-400">
                    {campaign.timezone}
                  </span>
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">
                  {campaign.max_concurrent_calls}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">
                  {campaign.max_retries}
                </td>
                <td className="px-3 py-2.5 text-right">
                  <Link
                    to={`/campaigns/${campaign.id}`}
                    className="text-sm font-medium text-brand-600 hover:text-brand-700"
                  >
                    Open
                  </Link>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {creating && <CampaignEditor onClose={() => setCreating(false)} />}
    </div>
  );
}

/** The API answers with a machine reason; a person needs the sentence. */
function dialSummary(result: DispatchResult): string {
  if (result.started > 0) {
    return `Dialling ${result.started} ${result.started === 1 ? "lead" : "leads"} now.`;
  }
  const reasons: Record<string, string> = {
    nothing_due:
      "Nobody is waiting to be called. Every lead on this campaign has been dialled.",
    completed: "This campaign is finished — every lead has been called.",
    at_concurrency_limit:
      "Already at the concurrent-call limit. These calls start as others end.",
    campaign_budget_reached:
      "The campaign budget cap is spent, so it has been paused.",
    budget_exceeded:
      "The account budget cap is spent, so the campaign has been paused.",
    outside_calling_hours: "Outside the calling window.",
  };
  const known = reasons[result.reason];
  return known ?? `No calls started (${result.reason.replace(/_/g, " ")}).`;
}

export function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: campaign, isLoading } = useCampaign(id);
  const control = useCampaignControl(id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [dialed, setDialed] = useState<DispatchResult | null>(null);

  if (isLoading || !campaign) {
    return <p className="py-10 text-center text-sm text-ink-500">Loading…</p>;
  }

  const act = async (action: "start" | "pause" | "stop" | "dispatch") => {
    setError(null);
    setDialed(null);
    try {
      const result = await control.mutateAsync(action);
      // A button that dials must say whether it dialled, and if not, why not.
      if (action === "dispatch") setDialed(result as DispatchResult);
    } catch (err) {
      setError(
        err instanceof ApiError || err instanceof NetworkError
          ? err.message
          : "Action failed",
      );
    }
  };

  const { stats } = campaign;
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            to="/campaigns"
            className="text-xs text-ink-500 hover:text-ink-700"
          >
            ← All campaigns
          </Link>
          <h1 className="mt-1 flex items-center gap-3 text-xl font-semibold text-ink-900">
            {campaign.name}
            <Badge value={campaign.status} />
          </h1>
        </div>
        <div className="flex gap-2">
          {campaign.status !== "running" && campaign.status !== "completed" && (
            <Button onClick={() => act("start")} loading={control.isPending}>
              Start
            </Button>
          )}
          {campaign.status === "running" && (
            <>
              <Button
                variant="secondary"
                onClick={() => act("dispatch")}
                loading={control.isPending}
              >
                Dial now
              </Button>
              <Button variant="secondary" onClick={() => act("pause")}>
                Pause
              </Button>
            </>
          )}
          {campaign.status !== "stopped" && campaign.status !== "completed" && (
            <Button
              variant="danger"
              onClick={() => {
                // A stopped campaign cannot be restarted, and it is one click
                // away from Pause. Say which is which before it happens.
                const live = stats.active_calls;
                if (
                  confirm(
                    `Stop "${campaign.name}" for good?\n\n` +
                      (live > 0
                        ? `${live} call(s) are live right now.\n`
                        : "") +
                      `${stats.pending} lead(s) will never be called.\n\n` +
                      "A stopped campaign cannot be restarted — use Pause if you only want a break.",
                  )
                ) {
                  act("stop");
                }
              }}
            >
              Stop
            </Button>
          )}
        </div>
      </header>

      {error && <Alert tone="error">{error}</Alert>}
      {dialed && (
        <Alert tone={dialed.started > 0 ? "success" : "warning"}>
          {dialSummary(dialed)}
        </Alert>
      )}
      {campaign.status === "running" && !stats.within_calling_hours && (
        <Alert tone="warning">
          Outside the configured calling window (
          {campaign.calling_hours_start.slice(0, 5)}–
          {campaign.calling_hours_end.slice(0, 5)} {campaign.timezone}), so the
          scheduler is not dialling. Use{" "}
          <span className="font-medium">Dial now</span> to call anyway.
        </Alert>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Leads"
          value={String(stats.total_leads)}
          hint={`${stats.pending} pending`}
        />
        <StatCard
          label="Calls made"
          value={String(stats.calls_made)}
          hint={`${stats.active_calls} live now`}
        />
        <StatCard
          label="Completed"
          value={String(stats.completed)}
          hint={`${stats.failed} failed`}
        />
        <StatCard label="Spend" value={formatCurrency(stats.cost_usd)} />
      </div>

      <Card title="Configuration">
        <dl className="grid gap-x-8 gap-y-2.5 text-sm sm:grid-cols-2">
          {[
            ["Max concurrent calls", String(campaign.max_concurrent_calls)],
            ["Delay between calls", `${campaign.delay_between_calls_seconds}s`],
            ["Max retries", String(campaign.max_retries)],
            ["Retry delay", `${campaign.retry_delay_minutes} min`],
            [
              "Calling window",
              `${campaign.calling_hours_start.slice(0, 5)}–${campaign.calling_hours_end.slice(0, 5)}`,
            ],
            ["Timezone", campaign.timezone],
            [
              "Budget cap",
              campaign.budget_limit_usd
                ? formatCurrency(campaign.budget_limit_usd)
                : "None",
            ],
          ].map(([label, value]) => (
            <div
              key={label}
              className="flex justify-between gap-4 border-b border-ink-100 py-1.5"
            >
              <dt className="text-ink-500">{label}</dt>
              <dd className="font-medium text-ink-900">{value}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <CampaignLeadList campaignId={campaign.id} callsMade={stats.calls_made} />
    </div>
  );
}

function CampaignEditor({ onClose }: { onClose: () => void }) {
  const { data: agents } = useAgents();
  const create = useCreateCampaign();
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "",
    agent_id: "",
    calling_hours_start: "10:00",
    calling_hours_end: "19:00",
    timezone: "Asia/Kolkata",
    max_concurrent_calls: 2,
    delay_between_calls_seconds: 5,
    max_retries: 2,
    retry_delay_minutes: 180,
    budget_limit_usd: "",
  });
  const [selected, setSelected] = useState<string[]>([]);

  const submit = async () => {
    setError(null);
    try {
      await create.mutateAsync({
        ...form,
        calling_hours_start: `${form.calling_hours_start}:00`,
        calling_hours_end: `${form.calling_hours_end}:00`,
        budget_limit_usd: form.budget_limit_usd
          ? Number(form.budget_limit_usd)
          : null,
        lead_ids: selected,
      });
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError || err instanceof NetworkError
          ? err.message
          : "Could not create the campaign",
      );
    }
  };

  return (
    <Modal open title="New campaign" onClose={onClose} wide>
      <div className="max-h-[70vh] space-y-4 overflow-y-auto pr-1">
        {error && <Alert tone="error">{error}</Alert>}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Campaign name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <Select
            label="Agent"
            value={form.agent_id}
            onChange={(e) => setForm({ ...form, agent_id: e.target.value })}
          >
            <option value="">Choose an agent…</option>
            {agents?.items.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </Select>
          <Field
            label="Calling hours start"
            type="time"
            value={form.calling_hours_start}
            onChange={(e) =>
              setForm({ ...form, calling_hours_start: e.target.value })
            }
          />
          <Field
            label="Calling hours end"
            type="time"
            value={form.calling_hours_end}
            onChange={(e) =>
              setForm({ ...form, calling_hours_end: e.target.value })
            }
            hint="Calls outside this window are never placed."
          />
          <Field
            label="Max concurrent calls"
            type="number"
            min="1"
            max="50"
            value={form.max_concurrent_calls}
            onChange={(e) =>
              setForm({ ...form, max_concurrent_calls: Number(e.target.value) })
            }
            hint="Start low. This is a spend limit as much as a throughput one."
          />
          <Field
            label="Delay between calls (s)"
            type="number"
            value={form.delay_between_calls_seconds}
            onChange={(e) =>
              setForm({
                ...form,
                delay_between_calls_seconds: Number(e.target.value),
              })
            }
          />
          <Field
            label="Max retries"
            type="number"
            value={form.max_retries}
            onChange={(e) =>
              setForm({ ...form, max_retries: Number(e.target.value) })
            }
          />
          <Field
            label="Retry delay (minutes)"
            type="number"
            value={form.retry_delay_minutes}
            onChange={(e) =>
              setForm({ ...form, retry_delay_minutes: Number(e.target.value) })
            }
          />
          <Field
            label="Budget cap (USD)"
            type="number"
            step="0.01"
            value={form.budget_limit_usd}
            onChange={(e) =>
              setForm({ ...form, budget_limit_usd: e.target.value })
            }
            hint="Optional. The campaign pauses itself when reached."
          />
        </div>

        <div className="space-y-2">
          <LeadPicker selected={selected} onChange={setSelected} />
          <p className="text-xs text-ink-400">
            Filter to a sheet, then use “Select all” to take the whole list. You
            can also upload a CSV to the campaign after creating it.
          </p>
        </div>
      </div>

      <footer className="mt-4 flex justify-end gap-2 border-t border-ink-100 pt-4">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button
          onClick={submit}
          loading={create.isPending}
          disabled={!form.name || !form.agent_id}
        >
          Create campaign
        </Button>
      </footer>
    </Modal>
  );
}

/** Counts alone leave people guessing; say what happened to their file. */
function importSummary(result: CampaignImportResult): string {
  if (result.attached === 0 && result.imported === 0) {
    return result.errors.length
      ? "Nothing was added from that file."
      : "Nobody new to add — everyone in that file is already on this campaign.";
  }
  const parts = [`${result.attached} on the call list`];
  if (result.imported) parts.push(`${result.imported} new to your leads`);
  const reused = result.attached - result.imported;
  if (reused > 0) parts.push(`${reused} already in your leads`);
  return `Added ${parts.join(", ")}.`;
}

function CampaignLeadList({
  campaignId,
  callsMade,
}: {
  campaignId: string;
  callsMade: number;
}) {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useCampaignLeads(campaignId, page);
  const [imported, setImported] = useState<CampaignImportResult | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const token = useAuthStore((state) => state.tokens?.access_token ?? null);
  const importLeads = useImportCampaignLeads(campaignId, token);
  const { data: sheetData } = useLeadLists();
  const sheets = sheetData ?? [];
  const addSheet = useAddSheetToCampaign(campaignId);
  const [note, setNote] = useState<string | null>(null);

  const pickFile = () => fileInput.current?.click();

  return (
    <Card
      title="Who is being called"
      description="Progress through the list, so you can see who is still waiting"
      actions={
        <div className="flex items-center gap-3">
          <input
            ref={fileInput}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              setImported(null);
              try {
                setImported(await importLeads.mutateAsync(file));
              } catch (error) {
                setImported({
                  imported: 0,
                  skipped: 0,
                  attached: 0,
                  errors: [
                    error instanceof Error ? error.message : "Upload failed",
                  ],
                });
              } finally {
                // Let the same file be picked again after a correction.
                event.target.value = "";
              }
            }}
          />
          {sheets.length > 0 && (
            <select
              value=""
              disabled={addSheet.isPending}
              onChange={(event) => {
                const id = event.target.value;
                if (!id) return;
                event.target.value = "";
                addSheet.mutate(id, {
                  onSuccess: (result) => setNote(result.message),
                });
              }}
              className="rounded-xl bg-white px-2.5 py-1.5 text-xs font-medium text-ink-700 shadow-card ring-1 ring-inset ring-ink-200 transition-colors hover:bg-ink-50"
            >
              <option value="">Add a sheet…</option>
              {sheets.map((sheet) => (
                <option key={sheet.id} value={sheet.id}>
                  {sheet.name} ({sheet.lead_count})
                </option>
              ))}
            </select>
          )}
          <Button
            size="sm"
            variant="secondary"
            onClick={pickFile}
            loading={importLeads.isPending}
          >
            Upload CSV
          </Button>
          <Link
            to={`/calls?campaign=${campaignId}`}
            className="text-xs font-medium text-brand-600 hover:text-brand-700"
          >
            View {callsMade} calls →
          </Link>
        </div>
      }
      flush
    >
      {note && (
        <div className="px-5 pt-4">
          <Alert tone="success">{note}</Alert>
        </div>
      )}
      {imported && (
        <div className="px-5 pt-4">
          <Alert tone={imported.errors.length ? "warning" : "success"}>
            {importSummary(imported)}
            {imported.errors.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs">
                {imported.errors.slice(0, 5).map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            )}
          </Alert>
        </div>
      )}
      {isLoading ? (
        <p className="px-5 py-8 text-center text-sm text-ink-500">Loading…</p>
      ) : !data?.items.length ? (
        <div className="px-5">
          <EmptyState
            title="No leads on this campaign"
            hint="Upload a CSV of the people you want called, or add existing leads."
          />
          <div className="flex justify-center gap-2 pb-8">
            <Button
              size="sm"
              onClick={pickFile}
              loading={importLeads.isPending}
            >
              Upload CSV
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() =>
                downloadCsv("leads-template.csv", leadTemplateCsv())
              }
            >
              Download template
            </Button>
          </div>
        </div>
      ) : (
        <div className="px-5 pb-4">
          <Table
            headers={[
              "Lead",
              "Status",
              "Attempts",
              "Last attempt",
              "Next attempt",
            ]}
          >
            {data.items.map((row) => (
              <tr key={row.id} className="hover:bg-ink-50">
                <td className="py-2.5 pl-5 pr-3">
                  <Link
                    to={`/leads?search=${row.lead_id}`}
                    className="font-medium text-ink-800 hover:text-brand-700"
                  >
                    <LeadName leadId={row.lead_id} />
                  </Link>
                </td>
                <td className="px-3 py-2.5">
                  <Badge value={row.status} />
                </td>
                <td className="px-3 py-2.5 tabular-nums text-ink-600">
                  {row.attempts}
                </td>
                <td className="px-3 py-2.5 text-xs text-ink-500">
                  {formatDateTime(row.last_attempt_at)}
                </td>
                <td className="px-3 py-2.5 text-xs text-ink-500">
                  {row.next_attempt_at
                    ? formatDateTime(row.next_attempt_at)
                    : "—"}
                </td>
              </tr>
            ))}
          </Table>
          <Pager
            page={data.page}
            pages={data.pages}
            total={data.total}
            onChange={setPage}
          />
        </div>
      )}
    </Card>
  );
}

/** Campaign membership stores only the lead id; show the name people know. */
function LeadName({ leadId }: { leadId: string }) {
  const { data } = useLead(leadId);
  return <>{data?.name ?? "…"}</>;
}
