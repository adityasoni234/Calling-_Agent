import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

/**
 * The rotating hero.
 *
 * Four slides, one per thing the product does, sitting on the page itself
 * rather than inside a tinted panel — the panel read as an advert dropped
 * onto the page instead of as the page's own opening.
 *
 * It slides horizontally on a transform, so the whole track moves as one
 * instead of text mutating in place. Three rules keep an auto-rotator from
 * being hostile: it stops on hover or focus, because a slide leaving
 * mid-sentence is worse than no rotation; it does not rotate at all under
 * prefers-reduced-motion; and the dots are real labelled buttons with arrow
 * keys, so it is not a keyboard trap.
 */

//: Two seconds, as asked. Short enough that hover-to-pause is doing real
//: work rather than being a nicety.
const SLIDE_MS = 2000;

interface Slide {
  eyebrow: string;
  title: string;
  body: string;
  points: string[];
}

const SLIDES: Slide[] = [
  {
    eyebrow: "English · हिन्दी · Hinglish",
    title: "An AI agent that talks to your customers in their own language.",
    body: "It calls in English, Hindi or Hinglish, and switches the moment the customer does — mid-sentence, without being told.",
    points: [
      "Holds a real conversation, not a phone tree",
      "Qualifies the lead and says why",
      "Hands you a transcript with the outcome",
    ],
  },
  {
    eyebrow: "SMS · WhatsApp",
    title: "Follow up on the channel they actually read.",
    body: "The same lead, texted and WhatsApped from one contact record — with approved templates, session windows and opt-outs handled for you.",
    points: [
      "Cost quoted before a single message sends",
      "STOP honoured the moment it arrives",
      "Delivery receipts, not hopeful guesses",
    ],
  },
  {
    eyebrow: "Email",
    title: "Send from your own address, checked before it goes.",
    body: "Connect your Gmail or Outlook in two clicks. Every address is validated first, and a bounce blocks it permanently.",
    points: [
      "Syntax, domain and suppression checked up front",
      "Hard bounces never retried",
      "Unsubscribe handled and honoured",
    ],
  },
  {
    eyebrow: "Leads · Meta Ads",
    title: "Every lead worked the day it arrives.",
    body: "Pull leads straight from your Facebook and Instagram forms, or upload a sheet. Duplicates merged, numbers normalised, nothing sitting idle.",
    points: [
      "Knows which campaign produced which lead",
      "Qualified ones surface first, with reasons",
      "One ledger for what it all cost",
    ],
  },
];

export function HeroCarousel() {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const reduced = useRef(false);

  useEffect(() => {
    reduced.current =
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    if (reduced.current) setPaused(true);
  }, []);

  const go = useCallback((next: number) => {
    setIndex(((next % SLIDES.length) + SLIDES.length) % SLIDES.length);
  }, []);

  useEffect(() => {
    if (paused) return;
    const timer = window.setInterval(
      () => setIndex((i) => (i + 1) % SLIDES.length),
      SLIDE_MS,
    );
    return () => window.clearInterval(timer);
  }, [paused]);

  return (
    <div
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => !reduced.current && setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight") go(index + 1);
        if (e.key === "ArrowLeft") go(index - 1);
      }}
      role="region"
      aria-roledescription="carousel"
      aria-label="What Stockvala does"
    >
      {/* The viewport clips; the track inside it slides. Overflow is hidden
          rather than scrollable so a trackpad swipe cannot desync the
          transform from the active dot. */}
      <div className="overflow-hidden">
        <div
          className="flex transition-transform duration-700 ease-[cubic-bezier(0.16,1,0.3,1)]"
          style={{ transform: `translateX(-${index * 100}%)` }}
        >
          {SLIDES.map((slide, i) => (
            <div
              key={slide.eyebrow}
              className="w-full shrink-0 pr-4"
              // Off-screen slides are hidden from assistive tech, or the
              // page reads as four competing headlines.
              aria-hidden={i !== index}
            >
              <p className="text-2xs font-medium uppercase tracking-[0.18em] text-brand-700">
                <span className="tracking-normal normal-case">
                  {slide.eyebrow}
                </span>
              </p>
              <h1 className="mt-5 max-w-3xl font-display text-4xl leading-[1.08] text-ink-900 sm:text-6xl">
                {slide.title}
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-relaxed text-ink-600">
                {slide.body}
              </p>
              <ul className="mt-7 grid max-w-3xl gap-2.5 sm:grid-cols-3">
                {slide.points.map((point) => (
                  <li
                    key={point}
                    className="flex gap-2.5 text-sm leading-relaxed text-ink-500"
                  >
                    <span aria-hidden className="text-brand-600">
                      —
                    </span>
                    {point}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      {/* Outside the track, so the buttons do not slide away from the cursor
          that is reaching for them. */}
      <div className="mt-9 flex flex-wrap items-center gap-3">
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
      </div>

      <div className="mt-8 flex items-center gap-2.5">
        {SLIDES.map((item, i) => (
          <button
            key={item.eyebrow}
            type="button"
            onClick={() => {
              go(i);
              setPaused(true);
            }}
            aria-label={`Show: ${item.eyebrow}`}
            aria-current={i === index}
            className={`h-1.5 rounded-full transition-all ${
              i === index
                ? "w-10 bg-brand-700"
                : "w-5 bg-ink-300 hover:bg-ink-400"
            }`}
          />
        ))}
      </div>
    </div>
  );
}
