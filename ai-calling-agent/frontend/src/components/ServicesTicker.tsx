import { SERVICES } from "@/components/services";

/**
 * The services, looping.
 *
 * Renders the list twice and slides the track by exactly half its width, so
 * the second copy arrives where the first began and the loop has no visible
 * seam. Duplicating in markup rather than cloning in JavaScript keeps it
 * working with no script at all.
 *
 * It pauses on hover, because a name someone is trying to read should not
 * slide away from them, and it stops entirely under prefers-reduced-motion:
 * a permanent horizontal crawl is exactly what that setting exists to
 * switch off.
 */

export function ServicesTicker() {
  const track = [...SERVICES, ...SERVICES];

  return (
    <div
      className="group relative overflow-hidden border-y border-ink-200/60 bg-white py-4"
      aria-label="Everything included"
    >
      {/* Fades the ends so items enter and leave rather than being chopped. */}
      <div className="pointer-events-none absolute inset-y-0 left-0 z-10 w-16 bg-gradient-to-r from-white to-transparent" />
      <div className="pointer-events-none absolute inset-y-0 right-0 z-10 w-16 bg-gradient-to-l from-white to-transparent" />

      <ul className="flex w-max animate-marquee items-center gap-10 group-hover:[animation-play-state:paused] motion-reduce:animate-none motion-reduce:flex-wrap motion-reduce:justify-center motion-reduce:px-5">
        {track.map((service, index) => (
          <li
            key={`${service.name}-${index}`}
            className="flex shrink-0 items-center gap-10"
            // The duplicate half is decoration; a screen reader announcing
            // every service twice is worse than it not announcing them here.
            aria-hidden={index >= SERVICES.length}
          >
            <span className="flex items-baseline gap-2.5 whitespace-nowrap">
              <span className="text-sm text-ink-900">{service.name}</span>
              <span className="text-2xs text-ink-400">{service.note}</span>
            </span>
            <span aria-hidden className="text-brand-600/50">
              ◆
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
