import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useHealth } from '@/hooks/useHealth'
import { initials } from '@/lib/format'
import { useAuthStore } from '@/stores/auth'

const NAV = [
  { to: '/', label: 'Overview', end: true, icon: 'M3 12l9-9 9 9M5 10v10h14V10' },
  { to: '/agents', label: 'AI Agents', icon: 'M12 3a4 4 0 100 8 4 4 0 000-8zM4 21v-1a6 6 0 016-6h4a6 6 0 016 6v1' },
  { to: '/leads', label: 'Leads', icon: 'M4 6h16M4 12h16M4 18h10' },
  { to: '/qualified', label: 'Qualified Leads', icon: 'M20 6L9 17l-5-5' },
  { to: '/campaigns', label: 'Campaigns', icon: 'M3 11l18-7-7 18-2-8-9-3z' },
  { to: '/calls', label: 'Calls', icon: 'M3 5a2 2 0 012-2h2l2 5-2 1a12 12 0 006 6l1-2 5 2v2a2 2 0 01-2 2A16 16 0 013 5z' },
  { to: '/knowledge', label: 'Knowledge Base', icon: 'M4 5a2 2 0 012-2h12v18H6a2 2 0 01-2-2V5zM8 7h8M8 11h8' },
  { to: '/settings', label: 'Settings', icon: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19 12a7 7 0 00-.1-1l2-1.5-2-3.5-2.3 1a7 7 0 00-1.7-1L14.5 3h-4l-.4 2.5a7 7 0 00-1.7 1l-2.3-1-2 3.5L6 11a7 7 0 000 2l-2 1.5 2 3.5 2.3-1a7 7 0 001.7 1l.4 2.5h4l.4-2.5a7 7 0 001.7-1l2.3 1 2-3.5-2-1.5c.06-.33.1-.66.1-1z' },
]

function Icon({ path }: { path: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-[18px] w-[18px] shrink-0"
      aria-hidden
    >
      <path d={path} />
    </svg>
  )
}

export function AppLayout() {
  const user = useAuthStore((state) => state.user)
  const logout = useAuthStore((state) => state.logout)
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const { data: health } = useHealth()

  // A menu that will not close on an outside click feels broken.
  useEffect(() => {
    if (!menuOpen) return
    const onClick = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [menuOpen])

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-ink-50">
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col bg-ink-deep lg:flex">
        <div className="flex h-16 items-center gap-2.5 px-6">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-brand-sheen text-xs font-bold text-white shadow-glow">
            AC
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-white">Calling Agent</p>
            <p className="text-2xs text-ink-400">{user?.organization?.name ?? ''}</p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 px-3 py-4">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all duration-150 ${
                  isActive
                    ? 'bg-white/[0.07] font-medium text-white'
                    : 'text-ink-400 hover:bg-white/[0.04] hover:text-ink-100'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-brand-400" />
                  )}
                  <Icon path={item.icon} />
                  {item.label}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="mx-3 mb-4 rounded-xl bg-white/[0.04] px-3.5 py-3">
          <div className="flex items-center gap-2 text-2xs text-ink-400">
            <span
              className={`relative flex h-2 w-2 ${health?.status === 'ok' ? '' : 'opacity-70'}`}
              aria-hidden
            >
              <span
                className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${
                  health?.status === 'ok' ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              />
              <span
                className={`relative inline-flex h-2 w-2 rounded-full ${
                  health?.status === 'ok' ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              />
            </span>
            API {health ? health.status : 'checking'}
            {health && <span className="ml-auto text-ink-500">v{health.version}</span>}
          </div>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-ink-200/70 bg-ink-50/80 px-5 backdrop-blur-xl lg:px-8">
          <div className="lg:hidden">
            <select
              aria-label="Navigate"
              className="rounded-xl border-0 bg-white py-2 pl-3 pr-8 text-sm shadow-card ring-1 ring-inset ring-ink-200"
              onChange={(event) => navigate(event.target.value)}
            >
              {NAV.map((item) => (
                <option key={item.to} value={item.to}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="relative ml-auto" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
              className="flex items-center gap-2.5 rounded-xl py-1.5 pl-1.5 pr-3 text-sm text-ink-700 transition-colors hover:bg-white hover:shadow-card"
            >
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-sheen text-2xs font-semibold text-white">
                {initials(user?.full_name ?? '?')}
              </span>
              <span className="hidden font-medium sm:inline">{user?.full_name}</span>
            </button>

            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 mt-2 w-60 animate-fade-up overflow-hidden rounded-2xl bg-white shadow-lift ring-1 ring-ink-200"
              >
                <div className="border-b border-ink-100 px-4 py-3">
                  <p className="truncate text-sm font-medium text-ink-900">{user?.email}</p>
                  <p className="mt-0.5 text-2xs capitalize text-ink-400">
                    {user?.role} · {user?.organization?.name}
                  </p>
                </div>
                <button
                  type="button"
                  role="menuitem"
                  onClick={handleLogout}
                  className="w-full px-4 py-2.5 text-left text-sm text-ink-700 transition-colors hover:bg-ink-50"
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        <main className="mx-auto max-w-[1400px] p-5 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
