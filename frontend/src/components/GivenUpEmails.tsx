import { useEffect, useState } from 'react'
import { api, errorMessage } from '../lib/api'
import { useToast } from '../lib/toast'
import { Button } from './ui/Button'
import { Message } from './ui/Message'

/** Emails the AI model failed on 3 times are skipped by scans; this lets the user have them read again. */
export function GivenUpEmails() {
  const toast = useToast()
  const [count, setCount] = useState(0)
  const [retrying, setRetrying] = useState(false)

  useEffect(() => {
    api
      .scanFailures()
      .then((r) => setCount(r.count))
      .catch(() => {}) // only a hint; the rest of the page works without it
  }, [])

  async function retry() {
    setRetrying(true)
    try {
      const { count: retried } = await api.retryScanFailures()
      setCount(0)
      toast('success', `The next scan will try ${retried === 1 ? 'that email' : `those ${retried} emails`} again.`)
    } catch (e) {
      toast('error', errorMessage(e))
    } finally {
      setRetrying(false)
    }
  }

  if (!count) return null
  return (
    <Message tone="warn">
      <div className="grid gap-2">
        <p className="text-ink">
          Squirrel couldn’t read {count === 1 ? '1 email' : `${count} emails`} after 3 tries, so scans skip{' '}
          {count === 1 ? 'it' : 'them'} now.
        </p>
        <div>
          <Button onClick={retry} loading={retrying} loadingLabel="Saving…">
            Try {count === 1 ? 'it' : 'them'} again
          </Button>
        </div>
      </div>
    </Message>
  )
}
