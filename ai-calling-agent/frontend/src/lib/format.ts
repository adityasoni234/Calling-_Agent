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
 * Money that arrived as integer minor units (paise, cents).
 *
 * The backend never sends a float for money, so the division belongs here --
 * exactly once -- rather than at each of the places that display a price.
 */
export function formatMinor(minor: number, currency = "INR"): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(minor / 100);
}

/** Credits are not money and should not look like it. */
export function formatCredits(credits: number): string {
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: credits < 100 ? 2 : 0,
  }).format(credits);
}
