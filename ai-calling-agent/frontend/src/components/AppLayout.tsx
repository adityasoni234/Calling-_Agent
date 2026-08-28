import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useHealth } from '@/hooks/useHealth'
import { initials } from '@/lib/format'
import { useAuthStore } from '@/stores/auth'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/agents', label: 'AI Agents' },
  { to: '/leads', label: 'Leads' },
  { to: '/campaigns', label: 'Campaigns' },
  { to: '/calls', label: 'Calls' },
  { to: '/knowledge', label: 'Knowledge Base' },
  { to: '/settings', label: 'Settings' },
]

export function AppLayout() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const { data: health } = useHealth()

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-slate-200 bg-white lg:flex">
        <div className="flex h-14 items-center gap-2 border-b border-slate-100 px-5">
          <span className="grid h-7 w-7 place-items-center rounded-lg bg-brand-600 text-xs font-bold text-white">
            AC
          </span>
          <span className="text-sm font-semibold text-slate-900">Calling Agent</span>
        </div>

        <nav className="flex-1 space-y-0.5 px-3 py-4">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive
                    ? 'bg-brand-50 font-medium text-brand-700'
                    : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">
          <span
            className={`mr-2 inline-block h-2 w-2 rounded-full ${
              health?.status === 'ok' ? 'bg-emerald-500' : 'bg-amber-500'
            }`}
            aria-hidden
          />
          API {health ? health.status : 'checking'}
          {health && <span className="ml-1 text-slate-400">v{health.version}</span>}
        </div>
      </aside>

      <div className="lg:pl-60">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-slate-200 bg-white/90 px-5 backdrop-blur">
          <div className="lg:hidden">
            <select
              aria-label="Navigate"
              className="rounded-lg border-slate-300 text-sm"
              onChange={(event) => navigate(event.target.value)}
            >
              {NAV.map((item) => (
                <option key={item.to} value={item.to}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="ml-auto relative">
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-100"
            >
              <span className="grid h-7 w-7 place-items-center rounded-full bg-slate-200 text-xs font-semibold text-slate-700">
                {initials(user?.full_name ?? '?')}
              </span>
              <span className="hidden sm:inline">{user?.full_name}</span>
            </button>

            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 mt-1 w-56 rounded-lg border border-slate-200 bg-white py-1 shadow-lg"
              >
                <div className="border-b border-slate-100 px-3 py-2">
                  <p className="truncate text-sm font-medium text-slate-900">{user?.email}</p>
                  <p className="text-xs capitalize text-slate-500">{user?.role}</p>
                </div>
                <button
                  type="button"
                  role="menuitem"
                  onClick={handleLogout}
                  className="w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        <main className="p-5 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
