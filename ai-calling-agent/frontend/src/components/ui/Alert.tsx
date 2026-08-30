import type { ReactNode } from 'react'

const TONES = {
  error: 'bg-red-50 text-red-800 ring-red-200',
  warning: 'bg-amber-50 text-amber-900 ring-amber-200',
  info: 'bg-brand-50 text-brand-900 ring-brand-200',
  success: 'bg-emerald-50 text-emerald-800 ring-emerald-200',
} as const

interface AlertProps {
  tone?: keyof typeof TONES
  children: ReactNode
}

export function Alert({ tone = 'info', children }: AlertProps) {
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`animate-fade-up rounded-xl px-4 py-3 text-sm leading-relaxed ring-1 ring-inset ${TONES[tone]}`}>
      {children}
    </div>
  )
}
