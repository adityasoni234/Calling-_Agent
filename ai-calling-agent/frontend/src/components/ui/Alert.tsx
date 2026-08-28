import type { ReactNode } from 'react'

const TONES = {
  error: 'border-red-200 bg-red-50 text-red-800',
  warning: 'border-amber-200 bg-amber-50 text-amber-900',
  info: 'border-slate-200 bg-slate-50 text-slate-700',
  success: 'border-emerald-200 bg-emerald-50 text-emerald-800',
} as const

interface AlertProps {
  tone?: keyof typeof TONES
  children: ReactNode
}

export function Alert({ tone = 'info', children }: AlertProps) {
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`rounded-lg border px-3.5 py-2.5 text-sm ${TONES[tone]}`}>
      {children}
    </div>
  )
}
