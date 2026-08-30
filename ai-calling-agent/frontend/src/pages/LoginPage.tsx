import { type FormEvent, useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'

import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Field } from '@/components/ui/Field'
import { ApiError } from '@/lib/api'
import { selectIsAuthenticated, useAuthStore } from '@/stores/auth'

export function LoginPage() {
  const login = useAuthStore((state) => state.login)
  const isAuthenticated = useAuthStore(selectIsAuthenticated)
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (isAuthenticated) return <Navigate to="/" replace />

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email.trim(), password)
      const from = (location.state as { from?: string } | null)?.from
      navigate(from && from !== '/login' ? from : '/', { replace: true })
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'Could not reach the server. Is the backend running?',
      )
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthShell title="Sign in" subtitle="Manage your AI calling agents, campaigns, and leads.">
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {error && <Alert tone="error">{error}</Alert>}

        <Field
          label="Email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <Button type="submit" loading={submitting} className="w-full">
          Sign in
        </Button>
      </form>

      <p className="mt-5 text-center text-sm text-ink-500">
        No account yet?{' '}
        <Link to="/register" className="font-medium text-brand-600 hover:text-brand-700">
          Create your organization
        </Link>
      </p>
    </AuthShell>
  )
}

export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-ink-deep px-4 py-10">
      {/* Two soft brand washes give the dark ground depth without a busy image. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -left-40 -top-40 h-[32rem] w-[32rem] rounded-full bg-brand-600/20 blur-[120px]"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 -right-32 h-[28rem] w-[28rem] rounded-full bg-brand-400/15 blur-[120px]"
      />

      <div className="relative w-full max-w-sm animate-fade-up">
        <div className="mb-8 text-center">
          <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-brand-sheen text-sm font-bold text-white shadow-glow">
            AC
          </span>
          <h1 className="mt-5 text-xl font-semibold text-white">{title}</h1>
          <p className="mt-1.5 text-sm text-ink-400">{subtitle}</p>
        </div>
        <div className="rounded-2xl bg-white p-6 shadow-lift ring-1 ring-white/10">{children}</div>
        <p className="mt-6 text-center text-2xs text-ink-500">
          Calls are recorded where enabled. Comply with local calling regulations.
        </p>
      </div>
    </div>
  )
}
