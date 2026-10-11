import { useState } from "react";

import {
  useCheckProvider,
  useProviders,
  useSaveProvider,
  useToggleProvider,
} from "@/admin/hooks";
import { Action, Empty, Metric, PageTitle, Panel, Pill } from "@/admin/ui";
import type { ProviderConnection } from "@/types/api";

/**
 * Provider credentials and health.
 *
 * Every field here is write-only. The server returns masked tails and never
 * plaintext, so this screen cannot show a key back even to the admin who
 * typed it -- which is the point: a page that can display a secret is a page
 * that can leak one.
 *
 * Saving does not mark a provider healthy. Only a real authenticated call to
 * the vendor does, because a mistyped key looks exactly like a correct one
 * until something tries to use it.
 */

const when = (value: string | null) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "never";

/** What each provider is for, in words rather than a slug. */
const PURPOSE: Record<string, string> = {
  twilio: "Places calls and sends SMS and WhatsApp.",
  plivo: "Alternative carrier. Cheaper for Indian numbers than Twilio.",
  anthropic: "The model the agent thinks with.",
  deepgram: "Turns what the caller says into text.",
  cartesia: "Turns the agent's replies into speech.",
  razorpay: "Takes card and UPI payments for credit top-ups.",
};

export function Providers() {
  const providers = useProviders();
  const save = useSaveProvider();
  const check = useCheckProvider();
  const toggle = useToggleProvider();

  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<Record<string, string>>({});

  const rows = providers.data ?? [];
  const live = rows.filter((p) => p.status === "healthy");
  const broken = rows.filter((p) => p.status === "degraded" && p.is_enabled);

  const submit = async (provider: ProviderConnection) => {
    setError(null);
    try {
      await save.mutateAsync({
        slug: provider.slug,
        // Only non-empty fields are sent. A blank one means "leave it", not
        // "clear it" -- the server treats it the same way.
        secrets: Object.fromEntries(
          Object.entries(draft).filter(([, value]) => value.trim()),
        ),
        is_enabled: true,
      });
      setEditing(null);
      setDraft({});
    } catch (err) {
      setError((err as Error)?.message ?? "Could not save those credentials");
    }
  };

  const runCheck = async (provider: ProviderConnection) => {
    const result = await check.mutateAsync(provider.id);
    setChecked((prev) => ({
      ...prev,
      [provider.slug]: `${result.ok ? "OK" : "Failed"} — ${result.detail}`,
    }));
  };

  const input =
    "w-full rounded-md border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-[0.75rem] text-slate-100 placeholder:text-slate-600 focus:border-slate-500 focus:outline-none";

  return (
    <div>
      <PageTitle
        title="Providers"
        description="Credentials are encrypted before they are stored and are never shown again."
      />

      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <Metric
          label="Verified"
          value={String(live.length)}
          sub={`of ${rows.length} integrations`}
          tone={live.length ? "good" : "neutral"}
        />
        <Metric
          label="Enabled but unverified"
          value={String(broken.length)}
          sub="Run a check to confirm the keys work"
          tone={broken.length ? "bad" : "good"}
        />
        <Metric
          label="Not set up"
          value={String(rows.filter((p) => p.status === "unconfigured").length)}
        />
      </div>

      {error && (
        <p className="mb-4 rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-[0.8rem] text-red-300">
          {error}
        </p>
      )}

      {providers.isPending ? (
        <Empty title="Loading…" />
      ) : (
        <div className="space-y-4">
          {rows.map((provider) => {
            const open = editing === provider.slug;
            const configured = Object.keys(provider.secret_hints).length > 0;
            return (
              <Panel
                key={provider.slug}
                title={provider.label}
                description={PURPOSE[provider.slug] ?? provider.kind}
                actions={
                  <div className="flex items-center gap-2">
                    <Pill value={provider.status} />
                    {configured && (
                      <Action
                        busy={check.isPending}
                        onClick={() => void runCheck(provider)}
                      >
                        Test connection
                      </Action>
                    )}
                    {configured && (
                      <Action
                        onClick={() =>
                          toggle.mutate({
                            id: provider.id,
                            enabled: !provider.is_enabled,
                          })
                        }
                      >
                        {provider.is_enabled ? "Disable" : "Enable"}
                      </Action>
                    )}
                    <Action
                      tone="primary"
                      onClick={() => {
                        setEditing(open ? null : provider.slug);
                        setDraft({});
                        setError(null);
                      }}
                    >
                      {open ? "Cancel" : configured ? "Rotate keys" : "Set up"}
                    </Action>
                  </div>
                }
              >
                <div className="space-y-3 px-4 py-3.5 text-[0.8rem]">
                  <div className="flex flex-wrap gap-x-8 gap-y-2 text-slate-400">
                    <span>
                      Last checked{" "}
                      <span className="text-slate-200">
                        {when(provider.last_checked_at)}
                      </span>
                    </span>
                    <span>
                      Keys last changed{" "}
                      <span className="text-slate-200">
                        {when(provider.secrets_rotated_at)}
                      </span>
                    </span>
                    {provider.docs_url && (
                      <a
                        href={provider.docs_url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-slate-400 underline hover:text-slate-200"
                      >
                        Where to find these
                      </a>
                    )}
                  </div>

                  {provider.status_detail && (
                    <p
                      className={
                        provider.status === "healthy"
                          ? "text-emerald-400"
                          : "text-amber-400"
                      }
                    >
                      {provider.status_detail}
                    </p>
                  )}
                  {checked[provider.slug] && (
                    <p
                      className={
                        checked[provider.slug].startsWith("OK")
                          ? "text-emerald-400"
                          : "text-red-400"
                      }
                    >
                      {checked[provider.slug]}
                    </p>
                  )}

                  {configured && !open && (
                    <div className="flex flex-wrap gap-x-6 gap-y-1 font-mono text-[0.7rem] text-slate-500">
                      {Object.entries(provider.secret_hints).map(
                        ([key, hint]) => (
                          <span key={key}>
                            {key}:{" "}
                            <span className="text-slate-300">{hint}</span>
                          </span>
                        ),
                      )}
                    </div>
                  )}

                  {open && (
                    <div className="space-y-3 border-t border-slate-800 pt-3.5">
                      <p className="text-[0.75rem] text-slate-500">
                        Leave a field blank to keep the key that is already
                        saved. Nothing you type here can be read back.
                      </p>
                      {[
                        ...provider.required_fields,
                        ...provider.optional_fields,
                      ].map((field) => (
                        <div key={field}>
                          <label
                            className="block text-[0.65rem] font-medium uppercase tracking-[0.1em] text-slate-500"
                            htmlFor={`${provider.slug}-${field}`}
                          >
                            {field.replace(/_/g, " ")}
                            {provider.required_fields.includes(field) && (
                              <span className="ml-1 text-red-400">*</span>
                            )}
                          </label>
                          <input
                            id={`${provider.slug}-${field}`}
                            type="password"
                            autoComplete="off"
                            className={`mt-1 ${input}`}
                            placeholder={
                              provider.secret_hints[field] ?? "not set"
                            }
                            value={draft[field] ?? ""}
                            onChange={(e) =>
                              setDraft((prev) => ({
                                ...prev,
                                [field]: e.target.value,
                              }))
                            }
                          />
                        </div>
                      ))}
                      <Action
                        tone="primary"
                        busy={save.isPending}
                        onClick={() => void submit(provider)}
                      >
                        Save and enable
                      </Action>
                    </div>
                  )}
                </div>
              </Panel>
            );
          })}
        </div>
      )}
    </div>
  );
}
