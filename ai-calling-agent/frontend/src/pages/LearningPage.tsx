import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard } from "@/components/ui/StatCard";
import { EmptyState } from "@/components/ui/Table";
import {
  useAgents,
  useDecideVariant,
  useEnableLearning,
  useLearningSummary,
  useProposeVariant,
  useVariants,
} from "@/hooks/api";
import { formatDateTime } from "@/lib/format";
import type { Variant } from "@/types/api";

const KIND_LABEL: Record<string, string> = {
  greeting: "Opening line",
  objection: "Objection response",
  style_rule: "Style rule",
};

/** Trials below this are noise, matching MIN_TRIALS_TO_JUDGE on the server. */
const ENOUGH_TRIALS = 25;

function RewardBar({ value, trials }: { value: number; trials: number }) {
  const settled = trials >= ENOUGH_TRIALS;
  const tone = !settled
    ? "bg-ink-300"
    : value >= 0.5
      ? "bg-emerald-500"
      : "bg-amber-500";
  return (
    <div className="flex items-center gap-2">
      <span className="w-9 text-right text-xs font-semibold tabular-nums text-ink-800">
        {Math.round(value * 100)}
      </span>
      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-ink-100">
        <span
          className={`block h-full rounded-full ${tone}`}
          style={{ width: `${value * 100}%` }}
        />
      </span>
      <span className="text-2xs text-ink-400">
        {trials} {trials === 1 ? "call" : "calls"}
        {!settled && " · too early"}
      </span>
    </div>
  );
}

function VariantRow({ variant }: { variant: Variant }) {
  const decide = useDecideVariant();
  const pending = variant.status === "candidate";

  return (
    <li className="px-5 py-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-2xs font-medium uppercase tracking-wider text-ink-400">
              {KIND_LABEL[variant.kind] ?? variant.kind}
            </span>
            {variant.slot && (
              <span className="text-2xs text-ink-400">· {variant.slot}</span>
            )}
            {variant.is_baseline && <Badge value="control" tone="blue" />}
            {variant.status === "retired" && (
              <Badge value="retired" tone="neutral" />
            )}
            {pending && <Badge value="awaiting approval" tone="amber" />}
          </div>
          <p className="mt-1.5 text-sm leading-relaxed text-ink-800">
            “{variant.content}”
          </p>
          {variant.rationale && (
            <p className="mt-1.5 text-xs leading-relaxed text-ink-500">
              {variant.rationale}
            </p>
          )}
          {variant.retired_reason && (
            <p className="mt-1.5 text-xs text-ink-400">
              Retired: {variant.retired_reason}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          {variant.status === "active" && (
            <RewardBar value={variant.mean_reward} trials={variant.trials} />
          )}
          {pending && (
            <div className="flex gap-1.5">
              <Button
                size="sm"
                loading={decide.isPending}
                onClick={() =>
                  decide.mutate({ id: variant.id, decision: "approve" })
                }
              >
                Use it
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  decide.mutate({ id: variant.id, decision: "reject" })
                }
              >
                Discard
              </Button>
            </div>
          )}
          {variant.last_used_at && variant.status === "active" && (
            <span className="text-2xs text-ink-400">
              last used {formatDateTime(variant.last_used_at)}
            </span>
          )}
        </div>
      </div>
    </li>
  );
}

export function LearningPage() {
  const { data: summaries, isLoading } = useLearningSummary();
  const { data: agents } = useAgents();
  const [agentId, setAgentId] = useState<string>("");
  const { data: variants } = useVariants(agentId || undefined);
  const enable = useEnableLearning();
  const propose = useProposeVariant();
  const [note, setNote] = useState<string | null>(null);

  const active = agents?.items.filter((a) => a.is_active) ?? [];
  const selected = agentId || summaries?.[0]?.agent_id || active[0]?.id || "";
  const summary = summaries?.find((s) => s.agent_id === selected);
  const rows = (variants ?? []).filter(
    (v) => !selected || v.agent_id === selected,
  );
  const pending = rows.filter((v) => v.status === "candidate");

  return (
    <div className="space-y-5">
      <PageHeader
        title="Learning"
        description="The agent tries different phrasings and keeps the ones that produce better calls. Every new wording is approved by you before a customer hears it."
        actions={
          selected ? (
            <Button
              variant="secondary"
              loading={propose.isPending}
              onClick={async () => {
                const made = await propose.mutateAsync(selected);
                setNote(
                  made.length
                    ? "Drafted a new opening from recent weak calls — review it below."
                    : "Not enough weak calls yet to learn from. Come back after more calls.",
                );
              }}
            >
              Draft an idea now
            </Button>
          ) : undefined
        }
      />

      {note && <Alert tone="info">{note}</Alert>}

      {isLoading ? (
        <p className="py-10 text-center text-sm text-ink-500">Loading…</p>
      ) : !summaries?.length ? (
        <Card>
          <EmptyState
            title="Learning is not on yet"
            hint="Turn it on for an agent and its current wording becomes the control. New phrasings are then measured against it, call by call."
            action={
              active.length ? (
                <div className="flex flex-wrap justify-center gap-2">
                  {active.map((agent) => (
                    <Button
                      key={agent.id}
                      variant="secondary"
                      loading={enable.isPending}
                      onClick={async () => {
                        const result = await enable.mutateAsync(agent.id);
                        setNote(result.message);
                      }}
                    >
                      Turn on for {agent.name}
                    </Button>
                  ))}
                </div>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <>
          {summaries.length > 1 && (
            <div className="flex flex-wrap gap-1.5">
              {summaries.map((s) => (
                <button
                  key={s.agent_id}
                  type="button"
                  onClick={() => setAgentId(s.agent_id)}
                  className={`rounded-xl px-3 py-1.5 text-xs font-medium transition-colors ${
                    s.agent_id === selected
                      ? "bg-brand-50 text-brand-700 ring-1 ring-inset ring-brand-200"
                      : "bg-white text-ink-600 ring-1 ring-inset ring-ink-200 hover:bg-ink-50"
                  }`}
                >
                  {s.agent_name}
                  {s.candidates > 0 && (
                    <span className="ml-1.5 rounded-full bg-amber-100 px-1.5 text-[0.65rem] text-amber-800">
                      {s.candidates}
                    </span>
                  )}
                </button>
              ))}
            </div>
          )}

          {summary && (
            <div className="grid gap-3 sm:grid-cols-4">
              <StatCard
                label="Calls scored"
                value={String(summary.scored_calls)}
                hint="Each one taught the engine something"
                accent
              />
              <StatCard
                label="Average result"
                value={
                  summary.average_reward === null
                    ? "—"
                    : `${Math.round(summary.average_reward * 100)}`
                }
                hint="Out of 100, across scored calls"
              />
              <StatCard
                label="In rotation"
                value={String(summary.active_variants)}
                hint="Phrasings competing right now"
              />
              <StatCard
                label="Awaiting you"
                value={String(summary.candidates)}
                hint="Proposals needing approval"
              />
            </div>
          )}

          {summary?.best &&
            summary.baseline &&
            summary.best.id !== summary.baseline.id && (
              <Alert
                tone={summary.best.trials >= ENOUGH_TRIALS ? "success" : "info"}
              >
                {summary.best.trials >= ENOUGH_TRIALS ? (
                  <>
                    A learned opening is beating your original by{" "}
                    <strong>
                      {Math.round(
                        (summary.best.mean_reward -
                          summary.baseline.mean_reward) *
                          100,
                      )}{" "}
                      points
                    </strong>{" "}
                    over {summary.best.trials} calls.
                  </>
                ) : (
                  <>
                    A learned opening is ahead so far, but only over{" "}
                    {summary.best.trials} calls — too few to trust yet.
                  </>
                )}
              </Alert>
            )}

          {pending.length > 0 && (
            <Card
              title={`${pending.length} proposal${pending.length === 1 ? "" : "s"} awaiting you`}
              description="Drafted from calls that went badly. Nothing here has been said to a customer."
              flush
            >
              <ul className="divide-y divide-ink-100">
                {pending.map((variant) => (
                  <VariantRow key={variant.id} variant={variant} />
                ))}
              </ul>
            </Card>
          )}

          <Card
            title="What the agent is trying"
            description="Scores are smoothed, so a phrasing that won its first call does not read as perfect."
            flush
          >
            {rows.filter((v) => v.status !== "candidate").length === 0 ? (
              <EmptyState title="Nothing in rotation yet" />
            ) : (
              <ul className="divide-y divide-ink-100">
                {rows
                  .filter((v) => v.status !== "candidate")
                  .sort((a, b) => b.mean_reward - a.mean_reward)
                  .map((variant) => (
                    <VariantRow key={variant.id} variant={variant} />
                  ))}
              </ul>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
