import { type FormEvent, useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'

import { Alert } from '@/components/ui/Alert'
import { Button } from '@/components/ui/Button'
import { Field } from '@/components/ui/Field'
import { AuthShell } from '@/pages/LoginPage'
import { ApiError } from '@/lib/api'
import { selectIsAuthenticated, useAuthStore } from '@/stores/auth'

export function RegisterPage() {
  const register = useAuthStore((state) => state.register)
  const isAuthenticated = useAuthStore(selectIsAuthenticated)
  const navigate = useNavigate()

  const [form, setForm] = useState({
    organization_name: '',
    full_name: '',
    email: '',
    password: '',
  })
  const [error, setError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)

  if (isAuthenticated) return <Navigate to="/" replace />

  const update = (key: keyof typeof form) => (event: { target: { value: string } }) =>
    setForm((current) => ({ ...current, [key]: event.target.value }))

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setFieldErrors({})
    setSubmitting(true)
    try {
      await register({ ...form, email: form.email.trim() })
      navigate('/', { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        setFieldErrors(err.fieldErrors)
        setError(Object.keys(err.fieldErrors).length ? null : err.message)
      } else {
        setError('Could not reach the server. Is the backend running?')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthShell title="Create your organization" subtitle="You'll be the owner of this workspace.">
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {error && <Alert tone="error">{error}</Alert>}

        <Field
          label="Company name"
          required
          value={form.organization_name}
          onChange={update('organization_name')}
          error={fieldErrors.organization_name}
        />
        <Field
          label="Your name"
          autoComplete="name"
          required
          value={form.full_name}
          onChange={update('full_name')}
          error={fieldErrors.full_name}
        />
        <Field
          label="Work email"
          type="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={update('email')}
          error={fieldErrors.email}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          value={form.password}
          onChange={update('password')}
          error={fieldErrors.password}
          hint="At least 10 characters, mixing letters with digits or symbols."
        />

        <Button type="submit" loading={submitting} className="w-full">
          Create account
        </Button>
      </form>

      <p className="mt-5 text-center text-sm text-slate-500">
        Already have an account?{' '}
        <Link to="/login" className="font-medium text-brand-600 hover:text-brand-700">
          Sign in
        </Link>
      </p>
    </AuthShell>
  )
}
