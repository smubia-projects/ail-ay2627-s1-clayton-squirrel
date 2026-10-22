import { ListOrdered, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { isQuotaError } from '../lib/aiApi'
import { api, errorMessage, type Digest } from '../lib/api'
import { cn } from '../lib/cn'
import { AiLabel } from './AiLabel'
import { Button } from './ui/Button'
import { Card, CardHeader } from './ui/Card'
import { Message } from './ui/Message'
import { Skeleton } from './ui/Skeleton'

const PIPS = [1, 2, 3, 4, 5]

function UrgencyPips({ score }: { score: number }) {
  return (
    <span role="img" aria-label={`Urgency ${score} of 5`} className="inline-flex gap-0.5">
      {PIPS.map((n) => (
        <span key={n} className={cn('size-2 rounded-sm', n <= score ? 'bg-primary' : 'bg-line')} />
      ))}
    </span>
  )
}

export function DigestCard() {
  const [digest, setDigest] = useState<Digest | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function generate() {
    setLoading(true)
    setError(null)
    try {
      setDigest(await api.digest())
    } catch (e) {
      // The rate-limit CTA / paused notice is shown as a modal instead.
      if (!isQuotaError(e)) setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card as="section" aria-labelledby="digest-title">
      <CardHeader icon={ListOrdered} title="This week’s digest" titleId="digest-title" />
      <div className="grid gap-4 p-5">
        <p className="text-sm text-ink-muted">
          AI ranks what needs your attention first, weighing how soon each benefit expires against what it’s worth.
        </p>
        <Button
          icon={<RefreshCw className="size-4" aria-hidden />}
          loading={loading}
          loadingLabel="Ranking…"
          onClick={generate}
        >
          {digest ? 'Regenerate digest' : 'Generate digest'}
        </Button>

        <div aria-live="polite" className="grid gap-3">
          {loading ? (
            <>
              <Skeleton />
              <Skeleton className="w-3/4" />
              <Skeleton className="h-12 w-full rounded-xl" />
            </>
          ) : error ? (
            <Message tone="error">{error}</Message>
          ) : digest ? (
            <>
              <AiLabel />
              <p className="animate-rise">{digest.digest_text}</p>
              <ol className="grid gap-2">
                {digest.ranked_benefits.map((r) => (
                  <li
                    key={`${r.provider}-${r.benefit_name}`}
                    className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 rounded-xl bg-surface-2 px-3.5 py-2.5"
                  >
                    <span className="font-semibold">{r.benefit_name}</span>
                    <UrgencyPips score={r.urgency_score} />
                    <span className="col-span-2 text-sm text-ink-muted">
                      {r.provider} · {r.reason}
                    </span>
                  </li>
                ))}
              </ol>
            </>
          ) : null}
        </div>
      </div>
    </Card>
  )
}
