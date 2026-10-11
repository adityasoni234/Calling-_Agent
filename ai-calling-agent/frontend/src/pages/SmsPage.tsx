import { useState } from "react";

import {
  Campaigns,
  History,
  Inbox,
  OptOuts,
  SendPanel,
  Tabs,
} from "@/components/messaging/shared";
import { Alert } from "@/components/ui/Alert";
import { PageHeader } from "@/components/ui/PageHeader";
import { useConversations, useMessagingReadiness } from "@/hooks/api";

/**
 * SMS.
 *
 * Its own page rather than a tab beside WhatsApp, because the two are not
 * the same product: SMS bills per segment and sends to anyone, WhatsApp
 * needs Meta-approved templates and respects a session window. One screen
 * trying to be both ends up explaining neither.
 */

const TABS = [
  { key: "send", label: "Send" },
  { key: "inbox", label: "Conversations" },
  { key: "campaigns", label: "Campaigns" },
  { key: "history", label: "Delivery reports" },
  { key: "optouts", label: "Opt-outs" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function SmsPage() {
  const [tab, setTab] = useState<TabKey>("send");
  const readiness = useMessagingReadiness();
  const conversations = useConversations("sms");
  const unread = (conversations.data?.items ?? []).reduce(
    (total, c) => total + c.unread_count,
    0,
  );

  const blockers = readiness.data?.sms.blockers ?? [];

  return (
    <div className="space-y-8">
      <PageHeader
        title="SMS"
        description="Charged per segment. A long or non-Latin message is several segments, and opted-out contacts are never messaged."
      />

      {blockers.length > 0 && (
        <Alert tone="warning">
          <strong className="font-medium">SMS is not ready to send.</strong>
          <ul className="mt-1.5 space-y-1">
            {blockers.map((blocker) => (
              <li key={blocker}>{blocker}</li>
            ))}
          </ul>
        </Alert>
      )}

      <Tabs
        tabs={TABS.map((t) =>
          t.key === "inbox" && unread ? { ...t, badge: unread } : t,
        )}
        active={tab}
        onChange={setTab}
      />

      {tab === "send" && <SendPanel channel="sms" />}
      {tab === "inbox" && <Inbox channel="sms" />}
      {tab === "campaigns" && <Campaigns channel="sms" />}
      {tab === "history" && <History channel="sms" />}
      {tab === "optouts" && <OptOuts />}
    </div>
  );
}
