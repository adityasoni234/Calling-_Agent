/** One credit is one US cent of list price, so money is always readable. */
export const money = (credits: number) => `$${(credits / 100).toFixed(2)}`;
