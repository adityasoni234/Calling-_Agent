import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

/**
 * The rotating hero.
 *
 * Four slides, one per thing the product actually does, advancing on their
 * own so a visitor who reads nothing still sees the breadth. Three rules
 * keep an auto-rotator from being hostile:
 *
 * It stops the moment someone interacts -- hover, focus, or picking a slide
 * by hand. A panel that slides away mid-sentence is worse than no rotation.
 *
 * It stops entirely under prefers-reduced-motion, which is exactly what that
 * setting is for, and shows the first slide with all four reachable by their
 * dots.
 *
 * The dots are real buttons with labels, so the thing is usable by keyboard
 * and announced properly rather than being a decorative carousel that traps
 * everyone else.
 */

const SLIDE_MS = 6000;

interface Slide {
  eyebrow: string;
  title: string;
  body: string;
  points: string[];
  tint: string;
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
    tint: "from-brand-700 to-brand-800",
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
    tint: "from-emerald-800 to-brand-800",
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
    tint: "from-ink-800 to-ink-900",
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
    tint: "from-brand-800 to-emerald-900",
  },
];

export function HeroCarousel() {
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const reduced = useRef(false);

  useEffect(() => {
    reduced.current = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)",
    ).matches;
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

  const slide = SLIDES[index];

  return (
    <div
      className="relative"
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
      <div
        className={`relative overflow-hidden rounded-3xl bg-gradient-to-br ${slide.tint} px-6 py-10 transition-all duration-700 sm:px-12 sm:py-14`}
      >
        <div
          aria-hidden
          className="pointer-events-none absolute -right-20 -top-28 h-72 w-72 rounded-full bg-white/10 blur-3xl"
        />

        {/* key forces a remount so each slide fades in rather than the text
            mutating in place, which reads as a glitch. */}
        <div key={index} className="animate-fade-up">
          <p className="text-2xs font-medium uppercase tracking-[0.18em] text-white/70">
            <span className="tracking-normal normal-case">{slide.eyebrow}</span>
          </p>
          <h1 className="mt-5 max-w-3xl font-display text-3xl leading-[1.1] text-white sm:text-5xl">
            {slide.title}
          </h1>
          <p className="mt-5 max-w-2xl text-base leading-relaxed text-white/80 sm:text-lg">
            {slide.body}
          </p>

          <ul className="mt-7 grid gap-2.5 sm:grid-cols-3">
            {slide.points.map((point) => (
              <li
                key={point}
                className="flex gap-2.5 text-sm leading-relaxed text-white/85"
              >
                <span aria-hidden className="text-white/50">
                  —
                </span>
                {point}
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-9 flex flex-wrap items-center gap-3">
          <Link
            to="/register"
            className="rounded-xl bg-white px-6 py-3 text-sm font-medium text-brand-800 transition-colors hover:bg-ink-50"
          >
            Start free
          </Link>
          <Link
            to="/login"
            className="rounded-xl px-5 py-3 text-sm font-medium text-white/80 ring-1 ring-inset ring-white/25 transition-colors hover:bg-white/10"
          >
            Log in
          </Link>
        </div>
      </div>

      <div className="mt-5 flex items-center gap-2.5">
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
        <span className="ml-2 text-2xs text-ink-400">
          {paused ? "Paused" : `${index + 1} of ${SLIDES.length}`}
        </span>
      </div>
    </div>
  );
}
