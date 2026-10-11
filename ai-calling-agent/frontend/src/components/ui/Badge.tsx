const TONES = {
  neutral: "bg-ink-100 text-ink-600 ring-ink-200",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-700 ring-amber-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  blue: "bg-brand-50 text-brand-700 ring-brand-200",
  purple: "bg-violet-50 text-violet-700 ring-violet-200",
} as const;

type Tone = keyof typeof TONES;

/** One mapping from domain status to colour, so every screen agrees. */
const STATUS_TONES: Record<string, Tone> = {
  completed: "green",
  in_progress: "blue",
  ringing: "blue",
  initiated: "neutral",
  failed: "red",
  no_answer: "amber",
  busy: "amber",
  canceled: "neutral",
  running: "green",
  paused: "amber",
  stopped: "red",
  draft: "neutral",
  new: "neutral",
  contacted: "blue",
  interested: "blue",
  qualified: "green",
  converted: "green",
  callback: "amber",
  not_interested: "red",
  do_not_call: "red",
  unreachable: "amber",
  ready: "green",
  pending: "neutral",
  processing: "blue",
  high: "green",
  medium: "amber",
  low: "neutral",
  unknown: "neutral",
  active: "green",
  inactive: "neutral",
  // Orders
  paid: "green",
  created: "neutral",
  refunded: "purple",
  cancelled: "neutral",
  // Credit ledger
  purchase: "green",
  grant: "blue",
  usage: "neutral",
  refund: "purple",
  adjustment: "amber",
  reversal: "red",
};

const PULSING = new Set(["in_progress", "ringing", "running", "processing"]);

export function Badge({ value, tone }: { value: string; tone?: Tone }) {
  const resolved = tone ?? STATUS_TONES[value] ?? "neutral";
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-2xs font-medium ring-1 ring-inset ${TONES[resolved]}`}
    >
      {/* A live state should look live. */}
      {PULSING.has(value) && (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      )}
      {value.replace(/_/g, " ")}
    </span>
  );
}
