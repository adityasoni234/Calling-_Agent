/**
 * The founder.
 *
 * A face and a reason to trust the thing matter more on a new product than
 * another feature list. The photograph is a drop-in: put a file at
 * `public/founder.jpg` and it appears; until then the initials stand in
 * rather than a broken image or a grey silhouette.
 *
 * Everything here is meant to be edited by the person it describes, so it
 * is plain constants at the top of the file rather than buried in markup.
 */

const FOUNDER = {
  name: "Aditya Soni",
  role: "Founder",
  // Shown under the name. Credentials that mean something to the reader,
  // not a list of everything ever done.
  credentials: ["Chairperson, IEEE SOUSB"],
  photo: "/founder.jpg",
  initials: "AS",
  // Replace with your own words. Kept short on purpose: a founder note that
  // runs long stops being read.
  paragraphs: [
    "I built Stockvala because following up on leads is the part everyone knows matters and nobody has time for. A list sits untouched for three days and the interest is gone.",
    "So the agent calls the same hour the lead arrives, in the language that person actually speaks, and tells you which conversations are worth your afternoon. Everything else — the texts, the WhatsApps, the email — runs off the same contact record.",
  ],
  // Optional. Leave a value empty and the link is not rendered.
  links: [
    { label: "LinkedIn", href: "" },
    { label: "Email", href: "" },
  ],
};

export function FounderSection() {
  return (
    <section id="founder" className="scroll-mt-20 border-t border-ink-200/60">
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8 sm:py-20">
        <div className="grid items-start gap-10 lg:grid-cols-[18rem_1fr]">
          <div>
            <div className="relative aspect-square w-48 overflow-hidden rounded-2xl bg-brand-50 sm:w-56">
              {/* Initials sit underneath; the photo covers them when it
                  loads. Hiding a broken <img> leaves the initials showing
                  rather than a torn-page icon. */}
              <span
                aria-hidden
                className="absolute inset-0 grid place-items-center font-display text-5xl text-brand-700"
              >
                {FOUNDER.initials}
              </span>
              <img
                src={FOUNDER.photo}
                alt={FOUNDER.name}
                className="relative h-full w-full object-cover"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
              />
            </div>
            <p className="mt-5 font-display text-xl text-ink-900">
              {FOUNDER.name}
            </p>
            <p className="mt-1 text-sm text-ink-500">{FOUNDER.role}</p>
            {FOUNDER.credentials.map((credential) => (
              <p key={credential} className="mt-1 text-xs text-brand-700">
                {credential}
              </p>
            ))}
            <div className="mt-4 flex gap-4">
              {FOUNDER.links
                .filter((link) => link.href)
                .map((link) => (
                  <a
                    key={link.label}
                    href={link.href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-ink-500 underline underline-offset-2 transition-colors hover:text-ink-800"
                  >
                    {link.label}
                  </a>
                ))}
            </div>
          </div>

          <div>
            <p className="text-2xs font-medium uppercase tracking-[0.18em] text-brand-700">
              Why this exists
            </p>
            <div className="mt-5 space-y-5">
              {FOUNDER.paragraphs.map((paragraph) => (
                <p
                  key={paragraph.slice(0, 24)}
                  className="max-w-2xl text-lg leading-relaxed text-ink-700"
                >
                  {paragraph}
                </p>
              ))}
            </div>
            <p className="mt-7 border-l-2 border-brand-600 pl-4 text-sm leading-relaxed text-ink-500">
              Built and run in India, for teams calling Indian numbers. Pricing
              is cost-plus and visible — you see what a call costs us and what
              you are charged, on the same screen.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
