import { useState } from "react";

import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatCard } from "@/components/ui/StatCard";
import { EmptyState, Pager, Table } from "@/components/ui/Table";
import {
  useCreditBalance,
  useCreditLedger,
  useOrders,
  usePackages,
  useStartCheckout,
  useUsage,
} from "@/hooks/api";
import { formatCredits, formatDateTime, formatMinor } from "@/lib/format";
import type { Checkout, CreditPackage } from "@/types/api";

/**
 * Credits and payments.
 *
 * One credit is 10 paise of list price. Calls are billed cost-plus rather
 * than at a flat per-minute rate, because a call to the UK costs six times
 * one to India and a single flat price cannot serve both honestly. The page leads with
 * what is spendable rather than the raw balance: money held against calls
 * already dialling cannot be spent twice, and a customer who sees only the
 * total will ask why a call was refused.
 */

/** Ledger kinds read as jargon otherwise. Colour comes from Badge's shared map. */
const LEDGER_LABELS: Record<string, string> = {
  purchase: "Purchase",
  grant: "Granted",
  usage: "Call",
  refund: "Refund",
  adjustment: "Adjustment",
  reversal: "Reversal",
};

export function BillingPage() {
  const balance = useCreditBalance();
  const packages = usePackages();
  const usage = useUsage(30);
  const [ledgerPage, setLedgerPage] = useState(1);
  const [ordersPage, setOrdersPage] = useState(1);
  const ledger = useCreditLedger(ledgerPage);
  const orders = useOrders(ordersPage);

  const checkout = useStartCheckout();
  const [pending, setPending] = useState<Checkout | null>(null);

  const buy = async (pkg: CreditPackage) => {
    const result = await checkout.mutateAsync(pkg.id);
    // Either way the order now exists. When a provider is live this is where
    // its checkout opens; until then the modal explains the state honestly.
    setPending(result);
  };

  const spendable = balance.data?.spendable ?? 0;
  const held = balance.data?.held ?? 0;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Billing & Credits"
        description="Credits are charged per second of connected call time — nothing for a number that never answered."
      />

      {balance.data?.is_suspended && (
        <Alert tone="error">
          <strong>Calling is paused on this account.</strong>{" "}
          {balance.data.suspended_reason ?? "Top up to resume."}
        </Alert>
      )}

      <div className="grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Available to spend"
          value={formatCredits(spendable)}
          hint={
            held > 0
              ? `${formatCredits(held)} held for calls in progress`
              : "Nothing on hold"
          }
          pending={balance.isPending}
          accent
        />
        <StatCard
          label="Total balance"
          value={formatCredits(balance.data?.balance ?? 0)}
          hint="Including credits held against live calls"
          pending={balance.isPending}
        />
        <StatCard
          label="Spent this month"
          value={formatCredits(balance.data?.consumed_this_month ?? 0)}
          hint={`${formatCredits(balance.data?.consumed_today ?? 0)} today`}
          pending={balance.isPending}
        />
        <StatCard
          label="Calls, last 30 days"
          value={String(usage.data?.total_calls ?? 0)}
          hint={`${formatCredits(usage.data?.total_credits ?? 0)} credits`}
          pending={usage.isPending}
        />
      </div>

      <Card
        title="Top up"
        description="Prices include GST. Credits never expire unless a package says otherwise."
      >
        {packages.isPending ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="skeleton h-44 rounded-xl" />
            ))}
          </div>
        ) : !packages.data?.length ? (
          <EmptyState
            title="No packages available"
            hint="Nothing is on sale right now. Contact us and we will add credits directly."
          />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {packages.data.map((pkg) => (
              <article
                key={pkg.id}
                className="flex flex-col rounded-xl border border-ink-200/70 p-5 transition hover:border-brand-600/60"
              >
                <h3 className="text-sm font-medium text-ink-900">{pkg.name}</h3>
                <p className="mt-3 font-display text-[1.75rem] leading-none tabular-nums text-ink-900">
                  {formatMinor(pkg.payable_minor, pkg.currency)}
                </p>
                <p className="mt-1.5 text-2xs text-ink-400">
                  {formatMinor(pkg.price_minor, pkg.currency)} +{" "}
                  {formatMinor(pkg.tax_minor, pkg.currency)} tax
                </p>
                <p className="mt-4 text-sm tabular-nums text-ink-700">
                  {formatCredits(pkg.total_credits)} credits
                </p>
                {pkg.bonus_credits > 0 && (
                  <p className="mt-1 text-2xs text-brand-700">
                    includes {formatCredits(pkg.bonus_credits)} bonus
                  </p>
                )}
                {pkg.description && (
                  <p className="mt-3 text-xs leading-relaxed text-ink-500">
                    {pkg.description}
                  </p>
                )}
                <div className="mt-auto pt-5">
                  <Button
                    variant="secondary"
                    className="w-full"
                    disabled={checkout.isPending}
                    onClick={() => void buy(pkg)}
                  >
                    {checkout.isPending ? "Starting…" : "Buy credits"}
                  </Button>
                </div>
              </article>
            ))}
          </div>
        )}
        {checkout.isError && (
          <Alert tone="error">
            {(checkout.error as Error)?.message ??
              "Could not start that purchase."}
          </Alert>
        )}
      </Card>

      <Card
        title="Credit history"
        description="Every movement, with the balance it left behind."
        flush
      >
        <div className="px-5">
          {!ledger.data?.items.length ? (
            <EmptyState
              title="Nothing yet"
              hint="Purchases, grants and call charges will appear here."
            />
          ) : (
            <>
              <Table
                headers={["When", "Type", "Change", "Balance after", "Note"]}
              >
                {ledger.data.items.map((entry) => {
                  return (
                    <tr key={entry.id}>
                      <td className="whitespace-nowrap text-ink-500">
                        {formatDateTime(entry.created_at)}
                      </td>
                      <td>{LEDGER_LABELS[entry.kind] ?? entry.kind}</td>
                      <td
                        className={`tabular-nums ${
                          entry.amount >= 0 ? "text-brand-700" : "text-ink-700"
                        }`}
                      >
                        {entry.amount >= 0 ? "+" : ""}
                        {formatCredits(entry.amount)}
                      </td>
                      <td className="tabular-nums text-ink-500">
                        {formatCredits(entry.balance_after)}
                      </td>
                      <td className="max-w-xs truncate text-ink-500">
                        {entry.note ?? "—"}
                      </td>
                    </tr>
                  );
                })}
              </Table>
              <Pager
                page={ledger.data.page}
                pages={ledger.data.pages}
                total={ledger.data.total}
                onChange={setLedgerPage}
              />
            </>
          )}
        </div>
      </Card>

      <Card
        title="Payments"
        description="Your orders and their receipts."
        flush
      >
        <div className="px-5">
          {!orders.data?.items.length ? (
            <EmptyState
              title="No payments yet"
              hint="Top up above to see receipts here."
            />
          ) : (
            <>
              <Table
                headers={[
                  "Reference",
                  "Package",
                  "Amount",
                  "Credits",
                  "Status",
                  "When",
                ]}
              >
                {orders.data.items.map((order) => (
                  <tr key={order.id}>
                    <td className="font-mono text-2xs text-ink-700">
                      {order.reference}
                    </td>
                    <td>{order.package_name}</td>
                    <td className="tabular-nums">
                      {formatMinor(order.total_minor, order.currency)}
                    </td>
                    <td className="tabular-nums text-ink-500">
                      {order.credits_allocated_at
                        ? formatCredits(order.total_credits)
                        : "—"}
                    </td>
                    <td>
                      <Badge value={order.status} />
                    </td>
                    <td className="whitespace-nowrap text-ink-500">
                      {formatDateTime(order.paid_at ?? order.created_at)}
                    </td>
                  </tr>
                ))}
              </Table>
              <Pager
                page={orders.data.page}
                pages={orders.data.pages}
                total={orders.data.total}
                onChange={setOrdersPage}
              />
            </>
          )}
        </div>
      </Card>

      <Modal
        open={pending !== null}
        title={
          pending?.provider_configured
            ? "Complete your payment"
            : "Order recorded"
        }
        onClose={() => setPending(null)}
      >
        {pending && (
          <div className="space-y-4 text-sm leading-relaxed text-ink-700">
            <div className="rounded-xl bg-ink-50 px-4 py-3">
              <p className="font-mono text-2xs text-ink-500">
                {pending.order.reference}
              </p>
              <p className="mt-1.5 text-ink-900">
                {pending.order.package_name} —{" "}
                {formatMinor(pending.order.total_minor, pending.order.currency)}{" "}
                for {formatCredits(pending.order.total_credits)} credits
              </p>
            </div>
            {pending.provider_configured ? (
              <p>
                Continue in the payment window. Credits are added once the
                payment clears.
              </p>
            ) : (
              <Alert tone="info">
                {pending.message ??
                  "Online payment is not set up yet. Your order has been recorded — contact us to complete it."}
              </Alert>
            )}
            <p className="text-xs text-ink-400">
              Credits are only ever added after the payment is verified with the
              provider directly.
            </p>
            <div className="flex justify-end">
              <Button variant="secondary" onClick={() => setPending(null)}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
