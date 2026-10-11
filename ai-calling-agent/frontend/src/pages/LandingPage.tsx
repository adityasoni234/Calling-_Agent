import { useEffect } from "react";
import { Link } from "react-router-dom";

import { useAuthStore } from "@/stores/auth";

/**
 * The public front door.
 *
 * The root URL used to be the login form, which asks a stranger to
 * authenticate before telling them what the product is. This page answers
 * that question first and sends them to login only once they want it.
 *
 * Deliberately has no data dependencies: it renders instantly for a visitor
 * with no session, and a slow or dead API cannot blank the marketing site.
 * Signed-in visitors get a "Go to dashboard" link rather than a redirect --
 * being bounced away from a page you meant to read is worse than one extra
 * click.
 */

const CHANNELS = [
  {
    name: "AI voice calls",
    body: "An agent that holds a real conversation, qualifies the lead, and hands over a transcript with the outcome.",
    icon: "M3 5a2 2 0 012-2h2l2 5-2 1a12 12 0 006 6l1-2 5 2v2a2 2 0 01-2 2A16 16 0 013 5z",
  },
  {
    name: "SMS",
    body: "One-off or bulk, billed per segment, with opt-outs honoured before anything leaves the building.",
    icon: "M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z",
  },
  {
    name: "WhatsApp",
    body: "Approved templates, the 24-hour session window, and delivery receipts — handled rather than explained.",
    icon: "M21 11.5a8.4 8.4 0 01-12.6 7.3L3 20.5l1.8-5.3A8.4 8.4 0 1121 11.5z",
  },
  {
    name: "Email",
    body: "Bulk campaigns with address validation up front, so you find the bad addresses before your sender reputation does.",
    icon: "M3 7a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7zm0 0l9 6 9-6",
  },
];

const STEPS = [
  {
    step: "01",
    title: "Bring your leads",
    body: "Upload a CSV, connect your Meta lead forms, or push them in over the API. Duplicates are merged, numbers normalised.",
  },
  {
    step: "02",
    title: "Describe your agent",
    body: "Say what it sells and what it must never claim. No prompt engineering, no flowchart builder.",
  },
  {
    step: "03",
    title: "Let it run",
    body: "It calls, texts and emails on a schedule you set, inside quiet hours, stopping the moment someone opts out.",
  },
  {
    step: "04",
    title: "Work the ones worth your time",
    body: "Qualified leads surface with the transcript and the reason. You spend your day on the short list.",
  },
];

const PROOF = [
  {
    figure: "3 languages",
    label: "English, Hindi and Hinglish — switched automatically, mid-call",
  },
  {
    figure: "Before you send",
    label: "Every campaign quotes its cost before a single message goes out",
  },
  {
    figure: "One ledger",
    label: "Every credit movement recorded, reconcilable, never rewritten",
  },
];

const FAQ = [
  {
    q: "Which languages can the agent speak?",
    a: "English, Hindi and Hinglish. You can pin an agent to one of them, or let it detect the language from the customer's first few words and follow them if they switch part-way through. It is the same agent and the same script either way — you do not maintain three versions.",
  },
  {
    q: "What does a call actually cost?",
    a: "You are charged per connected minute at your plan rate, and you see the figure before you dial. Calls that never connect cost nothing. Our own provider cost sits behind that, and the margin is shown to you rather than hidden in a bundle.",
  },
  {
    q: "Will it call people who asked not to be contacted?",
    a: "No. Opt-outs, do-not-call entries and withdrawn consent are checked before anything is dispatched, and the block is enforced on the server rather than in the screen you are looking at. A STOP reply suppresses the contact immediately.",
  },
  {
    q: "Do I need my own Twilio or Meta account?",
    a: "You can use ours to start. If you would rather bring your own, connect it in settings — credentials are encrypted and never shown again, including to us.",
  },
  {
    q: "What happens to recordings and transcripts?",
    a: "They stay inside your organization and are visible only to teammates whose role allows it. Recording is per-agent and off unless you turn it on, because the rules differ by country.",
  },
  {
    q: "Can I try it before paying?",
    a: "Yes. Every new account starts with trial credits — enough to run real calls and judge the thing rather than read about it.",
  },
];

function Icon({ path }: { path: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-5 w-5"
      aria-hidden
    >
      <path d={path} />
    </svg>
  );
}

export function LandingPage() {
  const signedIn = useAuthStore((state) => Boolean(state.tokens?.access_token));

  useEffect(() => {
    // Set here rather than in index.html so the marketing copy and the title
    // cannot drift apart, and so the app's own pages can override it.
    const previous = document.title;
    document.title =
      "Stockvala — AI calling, SMS, WhatsApp and email in one place";
    return () => {
      document.title = previous;
    };
  }, []);

  return (
    <div className="min-h-screen bg-ink-50 text-ink-800">
      <header className="sticky top-0 z-30 border-b border-ink-200/60 bg-ink-50/85 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4 sm:px-8">
          <div className="flex items-center gap-2.5">
            <span className="grid h-8 w-8 place-items-center rounded-xl bg-brand-700 text-xs font-semibold text-white">
              SV
            </span>
            <span className="font-display text-lg text-ink-900">Stockvala</span>
          </div>
          <nav className="flex items-center gap-1 sm:gap-3">
            <a
              href="#how"
              className="hidden rounded-xl px-3 py-2 text-sm text-ink-600 transition-colors hover:text-ink-900 sm:block"
            >
              How it works
            </a>
            <a
              href="#pricing"
              className="hidden rounded-xl px-3 py-2 text-sm text-ink-600 transition-colors hover:text-ink-900 sm:block"
            >
              Pricing
            </a>
            {signedIn ? (
              <Link
                to="/dashboard"
                className="rounded-xl bg-brand-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-800"
              >
                Go to dashboard
              </Link>
            ) : (
              <>
                <Link
                  to="/login"
                  className="rounded-xl px-3 py-2 text-sm text-ink-700 transition-colors hover:text-ink-900"
                >
                  Log in
                </Link>
                <Link
                  to="/register"
                  className="rounded-xl bg-brand-700 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-800"
                >
                  Start free
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main>
        {/* Hero */}
        <section className="mx-auto max-w-6xl px-5 pb-16 pt-16 sm:px-8 sm:pb-24 sm:pt-24">
          <p className="text-2xs font-medium uppercase tracking-[0.18em] text-brand-700">
            English ·{" "}
            {/* Letter-spacing pulls Devanagari conjuncts apart and uppercase
                does nothing to them, so this script opts out of both. */}
            <span className="tracking-normal normal-case">हिन्दी</span> ·
            Hinglish
          </p>
          <h1 className="mt-5 max-w-3xl font-display text-4xl leading-[1.08] text-ink-900 sm:text-6xl">
            An AI agent that talks to your customers in their own language.
          </h1>
          <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink-600">
            It calls in English, Hindi or Hinglish — and switches the moment the
            customer does, mid-sentence, without being told. Then it texts,
            WhatsApps and emails the same lead, and tells you which ones are
            worth your time.
          </p>
          {/* Someone already signed in is not a prospect. Offering them
              "Start free" next to a nav that says "Go to dashboard" reads as
              two different products. */}
          <div className="mt-9 flex flex-wrap items-center gap-3">
            {signedIn ? (
              <Link
                to="/dashboard"
                className="rounded-xl bg-brand-700 px-6 py-3 text-sm font-medium text-white shadow-sm transition-colors hover:bg-brand-800"
              >
                Go to your dashboard
              </Link>
            ) : (
              <>
                <Link
                  to="/register"
                  className="rounded-xl bg-brand-700 px-6 py-3 text-sm font-medium text-white shadow-sm transition-colors hover:bg-brand-800"
                >
                  Start free
                </Link>
                <Link
                  to="/login"
                  className="rounded-xl bg-white px-6 py-3 text-sm font-medium text-ink-700 ring-1 ring-inset ring-ink-300/70 transition-colors hover:bg-ink-50"
                >
                  Log in
                </Link>
                <span className="text-xs text-ink-400">
                  Trial credits included. No card to begin.
                </span>
              </>
            )}
          </div>

          <dl className="mt-16 grid gap-x-8 gap-y-6 border-t border-ink-200/70 pt-8 sm:grid-cols-3">
            {PROOF.map((item) => (
              <div key={item.figure}>
                <dt className="font-display text-xl text-ink-900">
                  {item.figure}
                </dt>
                <dd className="mt-1.5 text-sm leading-relaxed text-ink-500">
                  {item.label}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        {/* Language */}
        <section className="border-y border-ink-200/60 bg-brand-700">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
            <h2 className="max-w-2xl font-display text-3xl leading-tight text-white sm:text-4xl">
              Most people do not buy in their second language.
            </h2>
            <p className="mt-5 max-w-2xl text-base leading-relaxed text-white/75">
              A lead who answers in Hindi and gets an English script hangs up.
              Our agent hears which language they chose and answers in it —
              including the mix of both that most people actually speak.
            </p>

            <div className="mt-11 grid gap-x-10 gap-y-8 sm:grid-cols-3">
              {[
                {
                  lang: "English",
                  native: "English",
                  body: "Neutral Indian English, at the pace of a phone call rather than a voice assistant.",
                },
                {
                  lang: "Hindi",
                  native: "हिन्दी",
                  body: "Natural Hindi, not transliterated English read aloud.",
                },
                {
                  lang: "Hinglish",
                  native: "Hinglish",
                  body: "The way most of your customers genuinely talk — switching between the two inside a sentence.",
                },
              ].map((item) => (
                <div key={item.lang} className="border-t border-white/20 pt-5">
                  <p className="font-display text-2xl text-white">
                    {item.native}
                  </p>
                  <p className="mt-2 text-sm leading-relaxed text-white/70">
                    {item.body}
                  </p>
                </div>
              ))}
            </div>

            <div className="mt-11 rounded-2xl bg-white/10 px-6 py-5">
              <p className="text-2xs font-medium uppercase tracking-[0.1em] text-white/60">
                Automatic switching
              </p>
              <p className="mt-2.5 max-w-3xl text-sm leading-relaxed text-white/85">
                Set the agent to detect the language and it picks one up from
                the first few words, then follows the customer if they change.
                You can also pin it to a single language when you know your
                list.
              </p>
            </div>
          </div>
        </section>

        {/* Channels */}
        <section className="border-y border-ink-200/60 bg-white">
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
            <h2 className="font-display text-3xl text-ink-900">
              Four channels, one contact record
            </h2>
            <p className="mt-3 max-w-2xl text-base leading-relaxed text-ink-600">
              A lead who ignored your call, replied to your text and opened your
              email is one person — not three rows in three tools.
            </p>
            <div className="mt-10 grid gap-x-10 gap-y-9 sm:grid-cols-2">
              {CHANNELS.map((channel) => (
                <div key={channel.name} className="flex gap-4">
                  <span className="mt-0.5 grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-700">
                    <Icon path={channel.icon} />
                  </span>
                  <div>
                    <h3 className="text-base text-ink-900">{channel.name}</h3>
                    <p className="mt-1.5 text-sm leading-relaxed text-ink-600">
                      {channel.body}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section
          id="how"
          className="mx-auto max-w-6xl scroll-mt-20 px-5 py-16 sm:px-8 sm:py-24"
        >
          <h2 className="font-display text-3xl text-ink-900">How it works</h2>
          <div className="mt-10 grid gap-x-10 gap-y-10 sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((step) => (
              <div key={step.step} className="border-t border-ink-300/70 pt-5">
                <span className="font-display text-sm text-brand-700">
                  {step.step}
                </span>
                <h3 className="mt-2 text-base text-ink-900">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-ink-600">
                  {step.body}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* Pricing */}
        <section
          id="pricing"
          className="scroll-mt-20 border-y border-ink-200/60 bg-white"
        >
          <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
            <h2 className="font-display text-3xl text-ink-900">
              You see the price before you send
            </h2>
            <p className="mt-3 max-w-2xl text-base leading-relaxed text-ink-600">
              Prepaid credits, no monthly minimum, no per-seat fee. Every
              campaign quotes its cost before it runs, and calls that never
              connect are free.
            </p>

            <div className="mt-10 grid gap-5 sm:grid-cols-3">
              {[
                {
                  name: "Standard",
                  price: "$0.13",
                  note: "per connected minute",
                },
                {
                  name: "Premium",
                  price: "$0.15",
                  note: "managed, priority routing",
                },
                {
                  name: "Volume",
                  price: "Talk to us",
                  note: "negotiated floor",
                },
              ].map((plan, index) => (
                <div
                  key={plan.name}
                  className={`rounded-2xl p-6 ring-1 ${
                    index === 0
                      ? "bg-brand-700 text-white ring-brand-700"
                      : "bg-ink-50 ring-ink-200/70"
                  }`}
                >
                  <p
                    className={`text-2xs font-medium uppercase tracking-[0.1em] ${
                      index === 0 ? "text-white/70" : "text-ink-400"
                    }`}
                  >
                    {plan.name}
                  </p>
                  <p
                    className={`mt-3 font-display text-3xl ${
                      index === 0 ? "text-white" : "text-ink-900"
                    }`}
                  >
                    {plan.price}
                  </p>
                  <p
                    className={`mt-1.5 text-sm ${
                      index === 0 ? "text-white/70" : "text-ink-500"
                    }`}
                  >
                    {plan.note}
                  </p>
                </div>
              ))}
            </div>
            <p className="mt-5 text-xs leading-relaxed text-ink-400">
              SMS, WhatsApp and email are billed per message or segment at rates
              shown in the app before you send. Prices in USD.
            </p>
          </div>
        </section>

        {/* Trust */}
        <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
          <h2 className="font-display text-3xl text-ink-900">
            Built for people who have to answer for it afterwards
          </h2>
          <div className="mt-9 grid gap-x-10 gap-y-7 sm:grid-cols-2">
            {[
              [
                "Consent is a record, not a checkbox",
                "When and how someone agreed to be contacted is stored with the lead, because that is the question asked when a complaint arrives.",
              ],
              [
                "Opt-outs are enforced server-side",
                "A suppressed contact cannot be messaged by a campaign, an automation, or an API call. Not by anyone.",
              ],
              [
                "Credentials are encrypted, then invisible",
                "Provider keys are encrypted before storage and never returned by any API, log or export — including to us.",
              ],
              [
                "Every charge is traceable",
                "Each credit movement records what caused it and the balance it left. Past charges are never rewritten when prices change.",
              ],
            ].map(([title, body]) => (
              <div key={title}>
                <h3 className="text-base text-ink-900">{title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-600">
                  {body}
                </p>
              </div>
            ))}
          </div>
        </section>

        {/* FAQ */}
        <section className="border-t border-ink-200/60 bg-white">
          <div className="mx-auto max-w-3xl px-5 py-16 sm:px-8 sm:py-20">
            <h2 className="font-display text-3xl text-ink-900">Questions</h2>
            <div className="mt-8 divide-y divide-ink-200/70">
              {FAQ.map((item) => (
                <details key={item.q} className="group py-5">
                  <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-base text-ink-900">
                    {item.q}
                    <span
                      aria-hidden
                      className="shrink-0 text-ink-400 transition-transform group-open:rotate-45"
                    >
                      +
                    </span>
                  </summary>
                  <p className="mt-3 text-sm leading-relaxed text-ink-600">
                    {item.a}
                  </p>
                </details>
              ))}
            </div>
          </div>
        </section>

        {/* CTA */}
        <section className="mx-auto max-w-6xl px-5 py-20 sm:px-8">
          <div className="rounded-3xl bg-brand-700 px-7 py-14 text-center sm:px-12">
            <h2 className="font-display text-3xl text-white sm:text-4xl">
              Call your leads back today
            </h2>
            <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-white/75">
              Start with trial credits and run real calls. You will know within
              an afternoon whether it works for your list.
            </p>
            <Link
              to={signedIn ? "/dashboard" : "/register"}
              className="mt-8 inline-block rounded-xl bg-white px-7 py-3 text-sm font-medium text-brand-800 transition-colors hover:bg-ink-50"
            >
              {signedIn ? "Go to your dashboard" : "Start free"}
            </Link>
          </div>
        </section>
      </main>

      <footer className="border-t border-ink-200/60">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-5 py-8 text-xs text-ink-400 sm:px-8">
          <span>© {new Date().getFullYear()} Stockvala</span>
          <span>
            Calls are recorded where enabled. Comply with local calling and
            messaging regulations.
          </span>
        </div>
      </footer>
    </div>
  );
}
