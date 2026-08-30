import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-brand-sheen text-white shadow-glow hover:brightness-[1.07] active:brightness-95 focus-visible:outline-brand-600',
  secondary:
    'bg-white text-ink-700 ring-1 ring-inset ring-ink-200 shadow-card hover:bg-ink-50 hover:ring-ink-300 focus-visible:outline-ink-400',
  ghost: 'text-ink-500 hover:bg-ink-100 hover:text-ink-800 focus-visible:outline-ink-400',
  danger:
    'bg-red-600 text-white shadow-card hover:bg-red-700 active:bg-red-800 focus-visible:outline-red-600',
}

const SIZES: Record<Size, string> = {
  sm: 'px-2.5 py-1.5 text-xs gap-1.5',
  md: 'px-4 py-2.5 text-sm gap-2',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
  children: ReactNode
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled,
  className = '',
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      disabled={disabled ?? loading}
      className={`inline-flex select-none items-center justify-center rounded-xl font-medium transition-all duration-150 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
    >
      {loading && (
        <span
          aria-hidden
          className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  )
}
