/**
 * One credit is 10 paise (Rs0.10) of list price.
 *
 * It used to be one US cent while every package was priced in rupees, with
 * nothing converting between the two -- so the admin read dollars that were
 * never the currency anything was sold in.
 */
export const CREDITS_PER_INR = 10;

export const money = (credits: number) =>
  `₹${(credits / CREDITS_PER_INR).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
