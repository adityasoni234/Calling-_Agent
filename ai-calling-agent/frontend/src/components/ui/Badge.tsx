const TONES = {
  neutral: 'bg-slate-100 text-slate-700',
  green: 'bg-emerald-100 text-emerald-800',
  amber: 'bg-amber-100 text-amber-800',
  red: 'bg-red-100 text-red-800',
  blue: 'bg-brand-100 text-brand-800',
  purple: 'bg-violet-100 text-violet-800',
} as const

type Tone = keyof typeof TONES

/** One mapping from domain status to colour, so every screen agrees. */
const STATUS_TONES: Record<string, Tone> = {
  // calls
  completed: 'green',
  in_progress: 'blue',
  ringing: 'blue',
  initiated: 'neutral',
  failed: 'red',
  no_answer: 'amber',
  busy: 'amber',
  canceled: 'neutral',
  // campaigns
  running: 'green',
  paused: 'amber',
  stopped: 'red',
  draft: 'neutral',
  // leads
  new: 'neutral',
  contacted: 'blue',
  interested: 'blue',
  qualified: 'green',
  converted: 'green',
  callback: 'amber',
  not_interested: 'red',
  do_not_call: 'red',
  unreachable: 'amber',
  // documents
  ready: 'green',
  pending: 'neutral',
  processing: 'blue',
  // interest
  high: 'green',
  medium: 'amber',
  low: 'neutral',
  unknown: 'neutral',
}

export function Badge({ value, tone }: { value: string; tone?: Tone }) {
  const resolved = tone ?? STATUS_TONES[value] ?? 'neutral'
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${TONES[resolved]}`}
    >
      {value.replace(/_/g, ' ')}
    </span>
  )
}
