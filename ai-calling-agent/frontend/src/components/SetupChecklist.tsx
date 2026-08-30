import { Link } from 'react-router-dom'

import { Card } from '@/components/ui/Card'
import { useAgents, useCampaigns, useLeads, usePlatformSettings } from '@/hooks/api'

interface Step {
  label: string
  detail: string
  done: boolean
  to: string
  action: string
}

/**
 * Shows what to do next, and disappears once there is nothing left.
 *
 * The order here is not obvious from an empty dashboard: an agent is useless
 * without leads, leads do nothing without a campaign, and none of it dials
 * until a real telephony provider is configured.
 */
export function SetupChecklist() {
  const { data: agents } = useAgents()
  const { data: leads } = useLeads({ page: 1 })
  const { data: campaigns } = useCampaigns()
  const { data: settings } = usePlatformSettings()

  const steps: Step[] = [
    {
      label: 'Create your first agent',
      detail: 'Describe your business in a few lines and it writes the whole script for you.',
      done: (agents?.total ?? 0) > 0,
      to: '/agents',
      action: 'Create agent',
    },
    {
      label: 'Add the people to call',
      detail: 'Import a CSV from your CRM, or add a lead by hand to try it.',
      done: (leads?.total ?? 0) > 0,
      to: '/leads',
      action: 'Add leads',
    },
    {
      label: 'Connect a phone provider',
      detail: 'Until this is real, calls run on mocks and no phone rings.',
      done: settings ? !settings.using_mocks : false,
      to: '/settings',
      action: 'Check providers',
    },
    {
      label: 'Run a campaign',
      detail: 'Set calling hours and how many run at once, then start dialling.',
      done: (campaigns?.total ?? 0) > 0,
      to: '/campaigns',
      action: 'New campaign',
    },
  ]

  const remaining = steps.filter((step) => !step.done)
  if (remaining.length === 0) return null

  const next = remaining[0]

  return (
    <Card
      title="Get set up"
      description={`${steps.length - remaining.length} of ${steps.length} done — start with "${next.label.toLowerCase()}"`}
    >
      <ol className="space-y-1">
        {steps.map((step) => {
          const isNext = step === next
          return (
            <li key={step.label}>
              <Link
                to={step.to}
                className={`flex items-start gap-3.5 rounded-xl px-3 py-3 transition-colors ${
                  step.done ? 'opacity-55' : isNext ? 'bg-brand-50' : 'hover:bg-ink-50'
                }`}
              >
                <span
                  className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[10px] font-bold ${
                    step.done
                      ? 'bg-emerald-100 text-emerald-700'
                      : isNext
                        ? 'bg-brand-600 text-white'
                        : 'bg-ink-200 text-ink-500'
                  }`}
                >
                  {step.done ? '✓' : ''}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={`block text-sm font-medium ${step.done ? 'text-ink-500 line-through' : 'text-ink-900'}`}
                  >
                    {step.label}
                  </span>
                  {!step.done && (
                    <span className="mt-0.5 block text-xs leading-relaxed text-ink-500">
                      {step.detail}
                    </span>
                  )}
                </span>
                {isNext && (
                  <span className="shrink-0 self-center whitespace-nowrap rounded-lg bg-brand-600 px-2.5 py-1.5 text-2xs font-semibold text-white">
                    {step.action} →
                  </span>
                )}
              </Link>
            </li>
          )
        })}
      </ol>
    </Card>
  )
}
