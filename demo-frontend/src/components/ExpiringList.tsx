import { ArrowRight, Clock, Inbox, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import type { Benefit } from '../lib/api'
import { useToast } from '../lib/toast'
import { BenefitActions } from './BenefitActions'
import { BenefitRow } from './BenefitRow'
import { EditBenefitForm } from './EditBenefitForm'
import { Link } from './Link'
import { Button } from './ui/Button'
import { Card, CardHeader, CountChip } from './ui/Card'
import { Message } from './ui/Message'
import { Skeleton } from './ui/Skeleton'

interface ExpiringListProps {
  benefits: Benefit[] | null
  error: string | null
  onRetry: () => void
  onUpdated: (benefit: Benefit) => void
  onRemoved: (id: string) => void
  /** How many rows to show; the rest are on the All benefits page. */
  limit?: number
}

export function ExpiringList({ benefits, error, onRetry, onUpdated, onRemoved, limit = 5 }: ExpiringListProps) {
  const toast = useToast()
  const [editing, setEditing] = useState<string | null>(null)
  // Soonest first; a used-up card credit goes to the end until it resets.
  const sorted = benefits?.toSorted(
    (a, b) =>
      Number(Boolean(a.used_on)) - Number(Boolean(b.used_on)) ||
      (a.days_until_expiry ?? Infinity) - (b.days_until_expiry ?? Infinity),
  )

  return (
    <Card as="section" aria-labelledby="expiring-title">
      <CardHeader
        icon={Clock}
        title="Up next"
        titleId="expiring-title"
        action={sorted ? <CountChip>{sorted.length} total</CountChip> : null}
      />
      {error ? (
        <div className="grid gap-3 p-5">
          <Message tone="error">Couldn’t load your benefits: {error}</Message>
          <div>
            <Button icon={<RefreshCw className="size-4" aria-hidden />} onClick={onRetry}>
              Try again
            </Button>
          </div>
        </div>
      ) : !sorted ? (
        <ul aria-busy="true" aria-label="Loading benefits" className="divide-y divide-line">
          {['w-3/5', 'w-2/5', 'w-1/2'].map((width) => (
            <li key={width} className="grid gap-2 px-5 py-5">
              <Skeleton className={width} />
              <Skeleton className="w-1/3" />
            </li>
          ))}
        </ul>
      ) : sorted.length === 0 ? (
        <div className="grid justify-items-center gap-2 px-5 py-10 text-center text-ink-muted">
          <Inbox className="size-7" aria-hidden />
          <p className="font-semibold text-ink">Nothing tracked yet</p>
          <p>Paste a benefit email or add a credit card to start tracking benefits.</p>
          <Link href="/add" className="mt-1 font-semibold text-primary-text underline-offset-4 hover:underline">
            Add benefits
          </Link>
        </div>
      ) : (
        <>
          <ul className="divide-y divide-line">
            {sorted.slice(0, limit).map((b, i) =>
              editing === b.id ? (
                <EditBenefitForm
                  key={b.id}
                  benefit={b}
                  onCancel={() => setEditing(null)}
                  onSaved={(saved) => {
                    onUpdated(saved)
                    setEditing(null)
                    toast('success', `Saved “${saved.benefit_name}”.`)
                  }}
                />
              ) : (
                <BenefitRow key={b.id} benefit={b} index={i} showTerms={false}>
                  <BenefitActions
                    benefit={b}
                    onEdit={() => setEditing(b.id)}
                    onUpdated={onUpdated}
                    onRemoved={onRemoved}
                  />
                </BenefitRow>
              ),
            )}
          </ul>
          <div className="border-t border-line px-5 py-3">
            <Link
              href="/benefits"
              className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-primary-text underline-offset-4 hover:underline"
            >
              {sorted.length > limit ? `See all ${sorted.length} benefits` : 'Search, edit and filter your benefits'}
              <ArrowRight className="size-4" aria-hidden />
            </Link>
          </div>
        </>
      )}
    </Card>
  )
}
