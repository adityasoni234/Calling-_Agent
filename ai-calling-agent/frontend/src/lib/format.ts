export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return `${mins}m ${secs.toString().padStart(2, "0")}s`;
}

export function formatCurrency(amount: number, currency = "USD"): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    // Without this a non-US locale renders USD as "US$6.92". Everyone
    // reading a figure on their own dashboard knows the currency already.
    currencyDisplay: "narrowSymbol",
    maximumFractionDigits: amount < 1 ? 4 : 2,
  }).format(amount);
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

/**
 * Money that arrived as integer minor units (cents).
 *
 * The backend never sends a float for money, so the division belongs here --
 * exactly once -- rather than at each of the places that display a price.
 * The currency comes from the row being displayed, never from a default
 * guess: a package priced in USD rendered with a rupee sign is a support
 * ticket, and one rendered the other way is a refund.
 */
export function formatMinor(minor: number, currency = "USD"): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    // Without this, a non-US locale renders USD as "US$5.00". The audience
    // for a price tag already knows which currency they are being quoted.
    currencyDisplay: "narrowSymbol",
    maximumFractionDigits: 2,
  }).format(minor / 100);
}

/** Credits are not money and should not look like it. */
export function formatCredits(credits: number): string {
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: credits < 100 ? 2 : 0,
  }).format(credits);
}

/**
 * A USD amount that arrived from the API as a string.
 *
 * The backend sends six decimal places because a single AI charge really is
 * worth millionths of a dollar, but "$0.060000" on a screen reads as a bug.
 * Parsing to a number is safe *for display only* -- the authoritative value
 * stays the string, and nothing is written back from this.
 *
 * Trailing zeros are trimmed but real digits never are. Rounding a $0.015
 * WhatsApp message to "$0.01" would understate it by a third, and rounding
 * $0.0004 to "$0.00" would tell a customer a charge was free.
 */
export function formatUsd(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "number" ? value : Number.parseFloat(value);
  if (!Number.isFinite(amount)) return "—";

  const trimmed = amount
    .toFixed(6)
    .replace(/(\.\d*?)0+$/, "$1")
    .replace(/\.$/, "");
  const [whole, fraction = ""] = trimmed.split(".");
  // Cents are always shown: "$0.1" is not how money is written.
  return `$${whole}.${fraction.padEnd(2, "0")}`;
}
