/**
 * Why a message ended where it did, in words someone can act on.
 *
 * In its own module because a file that exports both components and
 * constants breaks React fast refresh.
 */
export const STATUS_HELP: Record<string, string> = {
  suppressed: "Blocked — this contact opted out",
  undelivered: "The carrier accepted it but could not deliver it",
  failed: "Rejected before sending",
  queued: "Waiting to be sent",
  sending: "Being handed to the carrier",
  sent: "Handed to the carrier",
  delivered: "Confirmed delivered",
  read: "Opened by the recipient",
};
