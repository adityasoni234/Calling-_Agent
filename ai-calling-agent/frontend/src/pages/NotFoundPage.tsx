import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="mx-auto max-w-md py-20 text-center">
      <p className="text-sm font-semibold text-brand-600">404</p>
      <h1 className="mt-2 text-xl font-semibold text-ink-900">Page not found</h1>
      <p className="mt-2 text-sm text-ink-500">That route doesn't exist in this workspace.</p>
      <Link
        to="/"
        className="mt-6 inline-block rounded-lg bg-brand-600 px-3.5 py-2 text-sm font-medium text-white hover:bg-brand-700"
      >
        Back to overview
      </Link>
    </div>
  )
}
