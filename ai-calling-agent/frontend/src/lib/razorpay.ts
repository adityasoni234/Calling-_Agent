/**
 * Opening Razorpay's hosted checkout.
 *
 * The widget is loaded from Razorpay's own CDN rather than bundled, because
 * it must be their current build: card network rules and the set of UPI apps
 * change under it, and a copy pinned at build time would quietly stop
 * accepting methods that still work everywhere else.
 *
 * Nothing secret passes through here. The server sends the publishable key
 * and an order id it has already created; the secret never leaves the
 * backend, and the handback this returns is proof of nothing until the
 * server has verified it.
 */

const SCRIPT_SRC = "https://checkout.razorpay.com/v1/checkout.js";

export interface CheckoutOptions {
  key: string;
  order_id: string;
  amount: number;
  currency: string;
  name?: string;
  description?: string;
  prefill?: { name?: string; email?: string; contact?: string };
}

/** Whatever Razorpay hands back. Verified server-side, never trusted here. */
export interface CheckoutHandback {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

interface RazorpayInstance {
  open: () => void;
  on: (event: string, handler: (payload: unknown) => void) => void;
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayInstance;
  }
}

let loader: Promise<void> | null = null;

/** Load once, even if two buttons are pressed before the first finishes. */
function loadScript(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  if (loader) return loader;

  loader = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${SCRIPT_SRC}"]`,
    );
    const script = existing ?? document.createElement("script");
    script.src = SCRIPT_SRC;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // Let the next attempt retry rather than caching the failure: this is
      // usually a dropped connection or a blocker, both of which change.
      loader = null;
      reject(
        new Error(
          "Could not reach Razorpay. Check your connection, or whether an " +
            "ad blocker is blocking checkout.razorpay.com.",
        ),
      );
    };
    if (!existing) document.head.appendChild(script);
  });
  return loader;
}

export class CheckoutDismissed extends Error {
  constructor() {
    super("Checkout was closed before payment finished");
    this.name = "CheckoutDismissed";
  }
}

/**
 * Open checkout and resolve with the handback.
 *
 * Dismissal rejects with `CheckoutDismissed` rather than resolving, because
 * the caller must not treat a closed window as a failed payment: the
 * customer may have paid and closed too early, and the webhook will settle
 * that. The order is left alone either way.
 */
export async function openCheckout(
  options: CheckoutOptions,
): Promise<CheckoutHandback> {
  await loadScript();
  const Razorpay = window.Razorpay;
  if (!Razorpay) throw new Error("Razorpay checkout failed to load");

  return new Promise<CheckoutHandback>((resolve, reject) => {
    let settled = false;

    const instance = new Razorpay({
      ...options,
      theme: { color: "#1f6f4a" },
      handler: (response: CheckoutHandback) => {
        settled = true;
        resolve(response);
      },
      modal: {
        ondismiss: () => {
          if (!settled) reject(new CheckoutDismissed());
        },
      },
    });

    instance.on("payment.failed", (payload: unknown) => {
      settled = true;
      const description = (
        payload as { error?: { description?: string } } | undefined
      )?.error?.description;
      reject(new Error(description ?? "The payment did not go through."));
    });

    instance.open();
  });
}
