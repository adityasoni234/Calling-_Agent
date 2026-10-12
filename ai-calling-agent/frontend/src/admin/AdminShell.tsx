import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useHealth } from "@/hooks/useHealth";
import { initials } from "@/lib/format";
import { useAuthStore } from "@/stores/auth";

const SECTIONS = [
  { to: "/", end: true, label: "Overview", icon: "M3 12h4l3 8 4-16 3 8h4" },
  {
    to: "/customers",
    label: "Customers",
    icon: "M3 21v-2a4 4 0 014-4h4a4 4 0 014 4v2M9 7a3 3 0 106 0 3 3 0 00-6 0M17 11h4M19 9v4",
  },
  {
    to: "/packages",
    label: "Packages",
    icon: "M3 7l9-4 9 4-9 4-9-4zM3 7v10l9 4 9-4V7M12 11v10",
  },
  {
    to: "/messages",
    label: "Messages",
    icon: "M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z",
  },
  {
    to: "/pricing",
    label: "Pricing",
    icon: "M12 1v22M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6",
  },
  {
    to: "/providers",
    label: "Providers",
    icon: "M12 2l8 4v6c0 4.5-3.2 8.3-8 10-4.8-1.7-8-5.5-8-10V6l8-4zM9 12l2 2 4-4",
  },
  {
    to: "/orders",
    label: "Orders",
    icon: "M3 3h2l2.4 11.2A2 2 0 009.3 16h7.4a2 2 0 002-1.6L20 7H6M9 20a1 1 0 100-2 1 1 0 000 2zM18 20a1 1 0 100-2 1 1 0 000 2z",
  },
  {
    to: "/users",
    label: "Users",
    icon: "M16 7a4 4 0 11-8 0 4 4 0 018 0zM3 21v-1a6 6 0 016-6h6a6 6 0 016 6v1",
  },
  {
    to: "/support-sessions",
    label: "Support access",
    icon: "M12 11a4 4 0 100-8 4 4 0 000 8zM4 21v-1a6 6 0 016-6h1M16 16l2 2 4-4",
  },
  {
    to: "/activity",
    label: "Activity",
    icon: "M12 8v4l3 2M12 3a9 9 0 110 18 9 9 0 010-18z",
  },
];

function Icon({ path }: { path: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="h-4 w-4 shrink-0"
      aria-hidden
    >
      <path d={path} />
    </svg>
  );
}

/**
 * The platform shell: dark, dense, and visibly not the customer product.
 *
 * Reusing the customer chrome made staff unsure which system they were looking
 * at, which is exactly the confusion you do not want in a tool that can suspend
 * a paying account.
 */
export function AdminShell() {
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const navigate = useNavigate();
  const { data: health } = useHealth();
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onClick = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node))
        setMenuOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [menuOpen]);

  const signOut = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  // A customer who reaches this build gets nothing and a way out.
  if (user && !user.is_platform_admin) {
    return (
      <div className="grid min-h-screen place-items-center bg-ink-50 px-4 text-center">
        <div className="max-w-sm">
          <h1 className="text-lg font-semibold text-ink-900">Not available</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-500">
            This account does not have platform access. Customers use the main
            dashboard.
          </p>
          <button
            type="button"
            onClick={signOut}
            className="mt-5 rounded-lg bg-brand-700 px-4 py-2 text-sm font-medium text-white"
          >
            Sign out
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-ink-50 text-ink-800">
      <aside className="fixed inset-y-0 left-0 hidden w-56 flex-col border-r border-ink-200/60 bg-white lg:flex">
        <div className="flex h-14 items-center gap-2.5 border-b border-ink-200/60 px-4">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-brand-700 text-[0.65rem] font-bold text-white">
            SV
          </span>
          <div className="leading-tight">
            <p className="text-xs font-semibold text-ink-900">Platform</p>
            <p className="text-[0.65rem] text-ink-400">Stockvala</p>
          </div>
        </div>

        <nav className="flex-1 space-y-0.5 p-2.5">
          {SECTIONS.map((section) => (
            <NavLink
              key={section.to}
              to={section.to}
              end={section.end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[0.8rem] transition-colors ${
                  isActive
                    ? "bg-ink-100 font-medium text-ink-900"
                    : "text-ink-500 hover:bg-ink-100/60 hover:text-ink-800"
                }`
              }
            >
              <Icon path={section.icon} />
              {section.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-ink-200/60 p-3">
          <p className="flex items-center gap-1.5 text-[0.65rem] text-ink-400">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                health?.status === "ok" ? "bg-emerald-500" : "bg-amber-500"
              }`}
            />
            API {health ? health.status : "checking"}
            {health && <span className="ml-auto">v{health.version}</span>}
          </p>
        </div>
      </aside>

      <div className="lg:pl-56">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-3 border-b border-ink-200/60 bg-ink-50/90 px-5 backdrop-blur lg:px-8">
          {/* You are acting on every customer. Say so, permanently. */}
          <span
            className="shrink-0 whitespace-nowrap rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-[0.65rem] font-medium uppercase tracking-wider text-amber-700"
            title="You are viewing data belonging to every customer"
          >
            {/* The warning has to survive a phone. Spelled out where there
                is room, abbreviated where there is not -- wrapping onto
                three lines ate the whole header. */}
            <span className="sm:hidden">All data</span>
            <span className="hidden sm:inline">All customer data</span>
          </span>

          <nav
            className="-mx-1 flex gap-1 overflow-x-auto px-1 lg:hidden"
            // Nine sections cannot sit side by side on a phone. A scrollable
            // rail keeps every label readable instead of shrinking them all
            // until none of them are.
            style={{ scrollbarWidth: "none" }}
          >
            {SECTIONS.map((section) => (
              <NavLink
                key={section.to}
                to={section.to}
                end={section.end}
                className={({ isActive }) =>
                  `shrink-0 whitespace-nowrap rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors ${
                    isActive
                      ? "bg-brand-700 text-white"
                      : "text-ink-500 hover:bg-ink-100"
                  }`
                }
              >
                {section.label}
              </NavLink>
            ))}
          </nav>

          <div className="relative lg:ml-auto" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-2.5 text-sm text-ink-700 transition-colors hover:bg-ink-100"
            >
              <span className="grid h-7 w-7 place-items-center rounded-md bg-ink-200 text-[0.65rem] font-semibold text-ink-900">
                {initials(user?.full_name ?? "?")}
              </span>
              <span className="hidden text-xs sm:inline">{user?.email}</span>
            </button>
            {menuOpen && (
              <div className="absolute right-0 mt-2 w-56 overflow-hidden rounded-lg border border-ink-200/60 bg-white">
                <div className="border-b border-ink-200/60 px-3 py-2.5">
                  <p className="truncate text-xs text-ink-800">{user?.email}</p>
                  <p className="mt-0.5 text-[0.65rem] text-ink-400">
                    Platform administrator
                  </p>
                </div>
                <button
                  type="button"
                  onClick={signOut}
                  className="w-full px-3 py-2 text-left text-xs text-ink-700 transition-colors hover:bg-ink-100"
                >
                  Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        <main className="mx-auto max-w-[1400px] px-4 py-5 sm:px-5 lg:px-8 lg:py-7">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
