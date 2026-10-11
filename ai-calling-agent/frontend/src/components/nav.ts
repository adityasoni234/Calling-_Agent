/**
 * The sidebar, grouped by what you are actually doing.
 *
 * Nine flat links gave no sense of which screens belong together, or which
 * ones you set up once versus live in daily. The grouping is the mental model
 * of the product: run the outreach, manage who you call, configure the rest.
 */
export interface NavItem {
  to: string;
  label: string;
  end?: boolean;
  icon: string;
  /** One line, shown in the mobile drawer and as a tooltip. */
  hint: string;
  /** Which live count to show as a badge, if any. */
  badge?: "qualified" | "running-campaigns";
  /** Platform staff only. Hidden from customers entirely. */
  platformOnly?: boolean;
}

export interface NavGroup {
  /** Null on the first group: a header above "Overview" is noise. */
  title: string | null;
  items: NavItem[];
}

export const NAV_GROUPS: NavGroup[] = [
  {
    title: null,
    items: [
      {
        to: "/",
        label: "Overview",
        end: true,
        hint: "Calls, spend and outcomes at a glance",
        icon: "M3 12l9-9 9 9M5 10v10h14V10",
      },
    ],
  },
  {
    title: "Outreach",
    items: [
      {
        to: "/campaigns",
        label: "Campaigns",
        hint: "Dial a list automatically, at a pace you set",
        badge: "running-campaigns",
        icon: "M3 11l18-7-7 18-2-8-9-3z",
      },
      {
        to: "/manual",
        label: "Manual Calling",
        hint: "Call a lead yourself — we ring your phone first",
        icon: "M3 5a2 2 0 012-2h2l2 5-2 1a12 12 0 006 6l1-2 5 2v2a2 2 0 01-2 2A16 16 0 013 5zM16 3h6m-3-3v6",
      },
      {
        to: "/calls",
        label: "Call History",
        hint: "Every call with its transcript, recording and cost",
        icon: "M12 8v4l3 2M12 3a9 9 0 110 18 9 9 0 010-18z",
      },
    ],
  },
  {
    title: "People",
    items: [
      {
        to: "/leads",
        label: "Leads",
        hint: "Everyone you can call, grouped by uploaded sheet",
        icon: "M16 7a4 4 0 11-8 0 4 4 0 018 0zM3 21v-1a6 6 0 016-6h6a6 6 0 016 6v1",
      },
      {
        to: "/qualified",
        label: "Qualified Leads",
        hint: "The ones worth a human call, best first",
        badge: "qualified",
        icon: "M9 12l2 2 4-4M12 3l7 4v5c0 4.4-3 8.3-7 9-4-.7-7-4.6-7-9V7l7-4z",
      },
    ],
  },
  {
    title: "Account",
    items: [
      {
        to: "/billing",
        label: "Billing & Credits",
        hint: "Your balance, top-ups and what each call cost",
        icon: "M3 10h18M3 7a2 2 0 012-2h14a2 2 0 012 2v10a2 2 0 01-2 2H5a2 2 0 01-2-2V7zM7 15h4",
      },
    ],
  },
  {
    title: "Setup",
    items: [
      {
        to: "/agents",
        label: "AI Agents",
        hint: "What the agent says, asks and must never claim",
        icon: "M12 2a3 3 0 013 3v1h1a4 4 0 014 4v4a6 6 0 01-6 6h-4a6 6 0 01-6-6v-4a4 4 0 014-4h1V5a3 3 0 013-3zM9 13h.01M15 13h.01",
      },
      {
        to: "/learning",
        label: "Learning",
        hint: "What the agent is trying, and what is working",
        icon: "M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17l9 5 9-5",
      },
      {
        to: "/knowledge",
        label: "Answers",
        hint: "Questions your agent can answer without checking",
        icon: "M4 5a2 2 0 012-2h12v18H6a2 2 0 01-2-2V5zM8 7h8M8 11h5",
      },
      {
        to: "/api",
        label: "API & Integrations",
        hint: "Keys and webhooks for plugging a CRM in",
        icon: "M10 20l4-16M6 8l-4 4 4 4M18 8l4 4-4 4",
      },
      {
        to: "/settings",
        label: "Settings",
        hint: "Providers, budgets, pricing and CRM integrations",
        icon: "M12 15a3 3 0 100-6 3 3 0 000 6zM19 12a7 7 0 00-.1-1l2-1.5-2-3.5-2.3 1a7 7 0 00-1.7-1L14.5 3h-4l-.4 2.5a7 7 0 00-1.7 1l-2.3-1-2 3.5L6 11a7 7 0 000 2l-2 1.5 2 3.5 2.3-1a7 7 0 001.7 1l.4 2.5h4l.4-2.5a7 7 0 001.7-1l2.3 1 2-3.5-2-1.5c.06-.33.1-.66.1-1z",
      },
    ],
  },
];

/** Flat list, for the mobile drawer and any lookup by path. */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((group) => group.items);
