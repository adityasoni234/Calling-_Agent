import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { SupportSessionBannerBar } from "@/components/SupportSessionBanner";

import { NAV_GROUPS, type NavItem } from "@/components/nav";
import { useCampaigns, useLeadCount, useUnreadCount } from "@/hooks/api";
import { useHealth } from "@/hooks/useHealth";
import { initials } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

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
  );
}

/** Counts worth seeing without opening the page. */
function useNavBadges() {
  const qualified = useLeadCount("qualified,converted");
  const unread = useUnreadCount();
  const campaigns = useCampaigns();
  const running = (campaigns.data?.items ?? []).filter(
    (campaign) => campaign.status === "running",
  ).length;
  return {
    qualified: qualified.data || undefined,
    "running-campaigns": running || undefined,
    "unread-messages": unread.data?.unread || undefined,
  } as Record<string, number | undefined>;
}

function NavRow({
  item,
  badge,
  onNavigate,
}: {
  item: NavItem;
  badge?: number;
  onNavigate?: () => void;
}) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={item.hint}
      onClick={onNavigate}
      className={({ isActive }) =>
        `group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-all duration-150 ${
          isActive
            ? "bg-brand-50 font-medium text-brand-800"
            : "text-ink-600 hover:bg-ink-100 hover:text-ink-900"
        }`
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-brand-600" />
          )}
          <Icon path={item.icon} />
          <span className="min-w-0 flex-1 truncate">{item.label}</span>
          {badge !== undefined && (
            <span
              className={`rounded-full px-1.5 py-0.5 text-[0.65rem] font-semibold tabular-nums ${
                isActive
                  ? "bg-brand-600 text-white"
                  : "bg-ink-200/80 text-ink-600"
              }`}
            >
              {badge > 999 ? "999+" : badge}
            </span>
          )}
        </>
      )}
    </NavLink>
  );
}

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const badges = useNavBadges();
  const isPlatformAdmin = useAuthStore((state) =>
    Boolean(state.user?.is_platform_admin),
  );
  // Drop platform-only groups entirely rather than rendering a disabled link:
  // a customer should not learn that an admin surface exists.
  const groups = NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => !item.platformOnly || isPlatformAdmin),
  })).filter((group) => group.items.length > 0);

  return (
    <nav className="flex-1 overflow-y-auto px-3 py-4">
      {groups.map((group, index) => (
        <div key={group.title ?? "main"} className={index > 0 ? "mt-5" : ""}>
          {group.title && (
            <p className="px-3 pb-1.5 text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-ink-400">
              {group.title}
            </p>
          )}
          <div className="space-y-0.5">
            {group.items.map((item) => (
              <NavRow
                key={item.to}
                item={item}
                badge={item.badge ? badges[item.badge] : undefined}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        </div>
      ))}
    </nav>
  );
}

function HealthPill() {
  const { data: health } = useHealth();
  const ok = health?.status === "ok";
  return (
    <div className="mx-3 mb-4 rounded-xl bg-ink-100/70 px-3.5 py-3">
      <div className="flex items-center gap-2 text-2xs text-ink-500">
        <span className="relative flex h-2 w-2" aria-hidden>
          <span
            className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${
              ok ? "bg-emerald-400" : "bg-amber-400"
            }`}
          />
          <span
            className={`relative inline-flex h-2 w-2 rounded-full ${
              ok ? "bg-emerald-400" : "bg-amber-400"
            }`}
          />
        </span>
        API {health ? health.status : "checking"}
        {health && (
          <span className="ml-auto text-ink-400">v{health.version}</span>
        )}
      </div>
    </div>
  );
}

function Brand({ organization }: { organization: string }) {
  return (
    <div className="flex h-16 items-center gap-2.5 px-6">
      <span className="grid h-8 w-8 place-items-center rounded-xl bg-brand-sheen text-xs font-bold text-white shadow-glow">
        AC
      </span>
      <div className="min-w-0 leading-tight">
        <p className="font-display text-base text-ink-900">Calling Agent</p>
        <p className="truncate text-2xs text-ink-500">{organization}</p>
      </div>
    </div>
  );
}

export function AppLayout() {
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // A menu that will not close on an outside click feels broken.
  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node))
        setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  // Navigating should dismiss the drawer, and Escape should always close it.
  useEffect(() => setDrawerOpen(false), [location.pathname]);
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (event: KeyboardEvent) =>
      event.key === "Escape" && setDrawerOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const organization = user?.organization?.name ?? "";

  return (
    <div className="min-h-screen bg-ink-50">
      {/* Above the sidebar and the header, so it is the first thing read on
          every page rather than something that scrolls out of sight. */}
      <SupportSessionBannerBar />
      <aside className="fixed inset-y-0 left-0 hidden w-64 flex-col border-r border-ink-200/70 bg-white lg:flex">
        <Brand organization={organization} />
        <SidebarNav />
        <HealthPill />
      </aside>

      {/* Mobile drawer. A <select> for navigation hid the structure entirely. */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setDrawerOpen(false)}
            className="absolute inset-0 bg-ink-900/50 backdrop-blur-sm"
          />
          <aside className="absolute inset-y-0 left-0 flex w-72 animate-slide-in flex-col border-r border-ink-200/70 bg-white shadow-lift">
            <Brand organization={organization} />
            <SidebarNav onNavigate={() => setDrawerOpen(false)} />
            <HealthPill />
          </aside>
        </div>
      )}

      <div className="lg:pl-64">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b border-ink-200/70 bg-ink-50/85 px-5 backdrop-blur-xl lg:px-8">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
            className="rounded-xl p-2 text-ink-600 transition-colors hover:bg-white hover:shadow-card lg:hidden"
          >
            <svg
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinecap="round"
              className="h-5 w-5"
              aria-hidden
            >
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          <div className="relative ml-auto" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-expanded={menuOpen}
              aria-haspopup="menu"
              className="flex items-center gap-2.5 rounded-xl py-1.5 pl-1.5 pr-3 text-sm text-ink-700 transition-colors hover:bg-white hover:shadow-card"
            >
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-sheen text-2xs font-semibold text-white">
                {initials(user?.full_name ?? "?")}
              </span>
              <span className="hidden font-medium sm:inline">
                {user?.full_name}
              </span>
            </button>

            {menuOpen && (
              <div
                role="menu"
                className="absolute right-0 mt-2 w-60 animate-fade-up overflow-hidden rounded-2xl bg-white shadow-lift ring-1 ring-ink-200"
              >
                <div className="border-b border-ink-100 px-4 py-3">
                  <p className="truncate text-sm font-medium text-ink-900">
                    {user?.email}
                  </p>
                  <p className="mt-0.5 text-2xs capitalize text-ink-400">
                    {user?.role} · {organization}
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

        <main className="mx-auto max-w-[1280px] space-y-6 p-5 lg:px-10 lg:py-9">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
