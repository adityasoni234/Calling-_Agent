/**
 * One credit is one US cent of list price.
 *
 * USD is the platform's commercial currency: provider invoices arrive in it,
 * prices are published in it, and margin is reported in it. A credit balance
 * is therefore readable as money with no conversion in anyone's head.
 */
export const CREDITS_PER_USD = 100;

export const money = (credits: number) =>
  `$${(credits / CREDITS_PER_USD).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
