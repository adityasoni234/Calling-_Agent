import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import { useRecording } from '@/hooks/api'

/**
 * Plays a call recording.
 *
 * Loads on demand rather than on page render: recordings are megabytes, and
 * most visits to a call are to read the transcript, not listen.
 */
export function RecordingPlayer({ callId }: { callId: string }) {
  const [requested, setRequested] = useState(false)
  const { data: src, isLoading, error } = useRecording(callId, requested)

  if (!requested) {
    return (
      <Button size="sm" variant="secondary" onClick={() => setRequested(true)}>
        Load recording
      </Button>
    )
  }

  if (isLoading) return <p className="text-sm text-ink-500">Loading audio…</p>

  if (error || !src) {
    return (
      <p className="text-sm text-ink-500">
        Not available yet — carriers publish recordings a few seconds after the call ends.
      </p>
    )
  }

  return <audio controls src={src} className="w-full" preload="none" />
}
