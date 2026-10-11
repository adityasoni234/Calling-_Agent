import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { PageHeader } from "@/components/ui/PageHeader";
import { EmptyState } from "@/components/ui/Table";
import {
  useMetaConnect,
  useMetaDisconnect,
  useMetaSelectAsset,
  useMetaStatus,
  useMetaSync,
} from "@/hooks/api";
import { formatDateTime } from "@/lib/format";
import type { MetaAssetRow, MetaConnectionRow } from "@/types/api";

/**
 * Connecting Meta lead ads.
 *
 * The authorisation happens on Facebook, not here: this page only opens the
 * official OAuth dialog and reports what came back. It never asks for a
 * token, because a page that accepts one is a page that can leak one — and
 * pasting long-lived tokens into forms is against Meta's terms anyway.
 *
 * Selecting a form is deliberately per-form. Connecting an account should
 * not start ingesting every lead the business has ever collected.
 */

export function MetaAdsPage() {
  const status = useMetaStatus();
  const connect = useMetaConnect();
  const data = status.data;

  const start = async () => {
    const { authorize_url } = await connect.mutateAsync();
    // A new tab rather than a redirect: the customer keeps their place, and
    // Meta's dialog sometimes refuses to render in an iframe.
    window.open(authorize_url, "_blank", "noopener,noreferrer");
  };

  return (
    <div className="space-y-8">
      <PageHeader
        title="Meta Ads"
        description="Pull leads from your Facebook and Instagram lead forms the moment someone submits one."
      />

      {data && !data.platform_configured && (
        <Alert tone="warning">
          <strong className="font-medium">Not available yet</strong>
          <ul className="mt-1.5 space-y-1">
            {data.blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </Alert>
      )}

      {!data?.connections.length ? (
        <div className="grid items-start gap-5 xl:grid-cols-2">
          <Card
            title="Connect your Meta account"
            description="You will be sent to Facebook to approve it. We never see your password, and you can disconnect at any time."
          >
            <div className="space-y-5">
              <Button
                disabled={!data?.platform_configured || connect.isPending}
                onClick={() => void start()}
              >
                {connect.isPending ? "Opening…" : "Connect with Facebook"}
              </Button>
              {connect.isError && (
                <Alert tone="error">
                  {(connect.error as Error)?.message ?? "Could not start."}
                </Alert>
              )}
              <div>
                <p className="text-xs font-medium text-ink-800">
                  What we ask permission for
                </p>
                <ul className="mt-2 space-y-1.5 text-xs leading-relaxed text-ink-600">
                  {(data?.required_scopes ?? []).map((scope) => (
                    <li key={scope} className="font-mono text-2xs">
                      {scope}
                    </li>
                  ))}
                </ul>
                <p className="mt-2.5 text-2xs leading-relaxed text-ink-500">
                  Enough to list your pages and read leads from the forms you
                  choose. Nothing here can post on your behalf or spend money.
                </p>
              </div>
            </div>
          </Card>

          <Card
            title="How it works"
            description="Four steps, then it runs on its own."
          >
            <ol className="space-y-4 text-sm leading-relaxed text-ink-700">
              {[
                "Approve access on Facebook. Your password never comes near us.",
                "Choose which lead forms to pull from — not every form on the page.",
                "Someone fills in your form on Facebook or Instagram.",
                "The lead appears in Leads within seconds, with the campaign that produced it.",
              ].map((step, index) => (
                <li key={step} className="flex gap-3">
                  <span className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-ink-100 text-2xs font-medium text-ink-600">
                    {index + 1}
                  </span>
                  <span>{step}</span>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      ) : (
        <div className="space-y-5">
          {data.connections.map((connection) => (
            <Connection key={connection.id} connection={connection} />
          ))}
        </div>
      )}
    </div>
  );
}

function Connection({ connection }: { connection: MetaConnectionRow }) {
  const sync = useMetaSync();
  const disconnect = useMetaDisconnect();

  const pages = connection.assets.filter((a) => a.kind === "page");
  const forms = connection.assets.filter((a) => a.kind === "lead_form");

  return (
    <Card
      title={connection.meta_user_name ?? "Meta account"}
      description={`Connected as ${connection.meta_user_name ?? "a Meta user"} · token ending ${connection.token_hint || "—"}`}
      actions={
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="secondary"
            disabled={sync.isPending}
            onClick={() => sync.mutate(connection.id)}
          >
            {sync.isPending ? "Syncing…" : "Refresh forms"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => disconnect.mutate(connection.id)}
          >
            Disconnect
          </Button>
        </div>
      }
    >
      <div className="space-y-5">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-xs text-ink-500">
          <span className="flex items-center gap-2">
            <Badge value={connection.status} />
          </span>
          <span>
            {connection.leads_received} lead
            {connection.leads_received === 1 ? "" : "s"} received
          </span>
          <span>Last lead {formatDateTime(connection.last_lead_at)}</span>
          <span>Synced {formatDateTime(connection.last_synced_at)}</span>
        </div>

        {!connection.is_usable && (
          <Alert tone="warning">
            {connection.status_detail ??
              "This connection has expired. Reconnect to keep receiving leads — we cannot refresh it from our side."}
          </Alert>
        )}

        {!forms.length ? (
          <EmptyState
            title="No lead forms found"
            hint={
              pages.length
                ? "Your pages have no lead forms yet. Create one in Meta, then press Refresh forms."
                : "No pages were returned. Check you granted access to the right business, then refresh."
            }
          />
        ) : (
          <div>
            <p className="text-xs font-medium text-ink-800">
              Choose which forms to pull leads from
            </p>
            <p className="mt-1 text-2xs leading-relaxed text-ink-500">
              Only the forms you tick are ingested. Nothing else on the account
              is touched.
            </p>
            <ul className="mt-4 divide-y divide-ink-200/60">
              {forms.map((form) => (
                <FormRow
                  key={form.id}
                  form={form}
                  page={pages.find((p) => p.meta_id === form.parent_meta_id)}
                />
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

function FormRow({ form, page }: { form: MetaAssetRow; page?: MetaAssetRow }) {
  const select = useMetaSelectAsset();

  return (
    <li className="flex items-center justify-between gap-4 py-3">
      <div className="min-w-0">
        <p className="truncate text-sm text-ink-900">{form.name}</p>
        <p className="mt-0.5 text-2xs text-ink-500">
          {page?.name ?? "Unknown page"}
          {form.is_selected && !form.is_subscribed && (
            <span className="ml-2 text-amber-700">
              · selected, but Meta has not confirmed the subscription
            </span>
          )}
          {form.is_selected && form.is_subscribed && (
            <span className="ml-2 text-brand-700">· receiving leads</span>
          )}
        </p>
      </div>
      <Button
        size="sm"
        variant={form.is_selected ? "ghost" : "secondary"}
        disabled={select.isPending}
        onClick={() =>
          select.mutate({ id: form.id, selected: !form.is_selected })
        }
      >
        {form.is_selected ? "Stop" : "Pull leads"}
      </Button>
    </li>
  );
}
