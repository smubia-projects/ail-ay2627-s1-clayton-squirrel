import { CreditCard, Sparkles } from 'lucide-react'
import type { Benefit } from '../lib/api'
import { creditLeft, formatMoney } from '../lib/usage'
import { Link } from './Link'

// The same plain gradients as the card stack on Connections, front card first.
const STRIPS = [
  'linear-gradient(120deg, #3B82F6, #1E3A8A)',
  'linear-gradient(120deg, #65A30D, #3F6212)',
  'linear-gradient(120deg, #475569, #1E293B)',
]

/** Card credits this period, as a small stack: the one with the most left is on top. */
function CreditsTile({ credits }: { credits: Benefit[] }) {
  const sorted = credits.toSorted((a, b) => creditLeft(b) - creditLeft(a))
  const top = sorted[0]
  return (
    <Link
      href="/benefits?kind=credit"
      className="glass grid animate-rise gap-3.5 rounded-[22px] p-5 transition-transform duration-150 hover:-translate-y-0.5"
      style={{ animationDelay: '120ms' }}
    >
      <span className="flex items-center justify-between gap-2 text-sm text-ink-muted">
        Card credits this period
        <span className="font-semibold text-ink">{credits.length}</span>
      </span>
      {top ? (
        <span className="relative block h-[104px]" aria-hidden>
          {sorted
            .slice(0, 3)
            .map((b, i) => (
              <span
                key={b.id}
                className="absolute flex h-[72px] flex-col justify-end rounded-[14px] px-3.5 py-2.5 text-white"
                style={{
                  left: `${i * 12}px`,
                  right: `${24 - i * 12}px`,
                  top: `${32 - i * 16}px`,
                  zIndex: 3 - i,
                  background: STRIPS[i],
                }}
              >
                {i === 0 ? (
                  <>
                    <span className="truncate text-xs text-[#DBEAFE]">{b.benefit_name}</span>
                    <span className="text-lg font-extrabold">
                      {formatMoney(creditLeft(b))} of {formatMoney(b.credit_total ?? 0)} left
                    </span>
                  </>
                ) : null}
              </span>
            ))
            .reverse()}
        </span>
      ) : null}
      {top ? (
        <span className="sr-only">
          {top.benefit_name}: {formatMoney(creditLeft(top))} of {formatMoney(top.credit_total ?? 0)} left
        </span>
      ) : null}
    </Link>
  )
}

/** Card credits (or a nudge to add a card) and a shortcut to the Assistant, beside "Up next". */
export function DashboardTiles({ benefits }: { benefits: Benefit[] | null }) {
  const credits = benefits?.filter((b) => b.credit_total != null) ?? []
  return (
    <div className="grid content-start gap-3">
      {credits.length ? (
        <CreditsTile credits={credits} />
      ) : benefits ? (
        <Link
          href="/add"
          className="glass flex animate-rise items-center gap-3.5 rounded-[22px] p-5 transition-transform duration-150 hover:-translate-y-0.5"
          style={{ animationDelay: '120ms' }}
        >
          <CreditCard className="size-7 shrink-0 text-ink-muted" aria-hidden />
          <span className="grid">
            <span className="font-bold">Add a credit card</span>
            <span className="text-sm text-ink-muted">Track its monthly credits and perks</span>
          </span>
        </Link>
      ) : null}
      <Link
        href="/assistant"
        className="grid min-h-[140px] animate-rise content-between gap-4 rounded-[22px] border border-primary/30 bg-primary-soft p-5 transition-transform duration-150 hover:-translate-y-0.5"
        style={{ animationDelay: '160ms' }}
      >
        <Sparkles className="size-7 text-primary-text" aria-hidden />
        <span className="text-xl leading-tight font-extrabold">Ask Squirrel what to use this week</span>
      </Link>
    </div>
  )
}
