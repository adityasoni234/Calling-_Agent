/**
 * What the platform actually does, in one list.
 *
 * Shared by the looping ticker and the grid beneath it so the two cannot
 * disagree, and in its own module because a file exporting both components
 * and constants breaks React fast refresh.
 *
 * Only capabilities that exist today. Anything still being built belongs on
 * a roadmap, not on a page that reads as a promise.
 */
export interface Service {
  name: string;
  note: string;
}

export const SERVICES: Service[] = [
  { name: "AI voice calls", note: "English, Hindi and Hinglish" },
  {
    name: "Automatic language switching",
    note: "Follows the customer mid-call",
  },
  { name: "SMS", note: "Single and bulk, billed per segment" },
  { name: "WhatsApp", note: "Approved templates and sessions" },
  { name: "Email campaigns", note: "Validated before a single send" },
  { name: "Address validation", note: "Syntax, domain and suppression" },
  { name: "Lead management", note: "Sheets, dedupe, pipeline" },
  { name: "Qualified-lead scoring", note: "The short list, with reasons" },
  { name: "Call recordings", note: "Where your rules allow it" },
  { name: "Transcripts", note: "Every call, searchable" },
  { name: "Outbound campaigns", note: "Paced, pausable, resumable" },
  { name: "Opt-out and DND", note: "Enforced server-side" },
  { name: "Consent records", note: "Dated, with the source" },
  { name: "Knowledge base", note: "Answers the agent can rely on" },
  { name: "Learning engine", note: "Improves from real outcomes" },
  { name: "Prepaid credits", note: "Priced before you send" },
  { name: "Usage and margin reporting", note: "Cost against revenue" },
  { name: "REST API and webhooks", note: "Plug your CRM in" },
];
