import { ExternalLink, TriangleAlert } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { CATEGORIES, type Benefit } from '../lib/api'
import { categoryHue } from '../lib/categories'
import { cn } from '../lib/cn'
import { capitalize, formatDate, formatPoints, reminderLabel, urgency } from '../lib/format'
import { creditLeft, formatMoney, usageKind } from '../lib/usage'
import { Link } from './Link'

// The coloured top of a ticket, by category, dark enough for white text in both themes.
function bandColor(b: Benefit) {
  const hue = categoryHue(b.category)
  return hue == null ? 'oklch(0.42 0.03 260)' : `oklch(0.47 0.12 ${hue})`
}

/** The big line on a ticket: what it's worth, if that's short; else its name. */
function headline(b: Benefit) {
  if (b.points != null) return formatPoints(b.points, b.points_unit)
  if (b.credit_total != null) return `${formatMoney(creditLeft(b))} left`
  if (b.value && b.value.length <= 14) return b.value
  return null
}

function status(b: Benefit) {
  if (b.needs_review) return 'To review'
  if (b.credit_total != null && creditLeft(b) === 0) return 'Used up'
  return urgency(b.days_until_expiry).label
}

function expiryLine(b: Benefit) {
  if (!b.expiry_date) return 'No expiry'
  const date = formatDate(b.expiry_date)
  if (usageKind(b) === 'credit') return `Resets after ${date}`
  return (b.days_until_expiry ?? 0) < 0 ? `Expired ${date}` : `Expires ${date}`
}

const SOURCES: Record<Benefit['source'], string> = {
  card: 'Card perk',
  email: 'An email you added',
  gmail: 'Gmail',
  outlook: 'Outlook',
  imap: 'Email',
  loyalty: 'Membership found in your email',
  manual: 'Added by you',
}

/** The top half: provider, status, the big value and the name. `tall` is the detail panel's bigger version. */
function Band({ benefit, tall }: { benefit: Benefit; tall?: boolean }) {
  const big = headline(benefit)
  const name = benefit.benefit_name || 'Untitled benefit'
  return (
    <div
      className={cn('flex flex-col justify-between gap-1.5 text-white', tall ? 'h-[176px] p-6' : 'h-[124px] p-4')}
      style={{ background: bandColor(benefit) }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-semibold tracking-[0.06em] uppercase">
          {benefit.provider || CATEGORIES[benefit.category]}
        </span>
        <span className="shrink-0 rounded-full bg-white/22 px-2.5 py-0.5 text-xs font-bold whitespace-nowrap">
          {status(benefit)}
        </span>
      </div>
      {big ? (
        <span
          className={cn(
            'truncate leading-none font-extrabold tracking-[-0.04em]',
            tall ? 'text-[56px]' : 'text-[34px]',
          )}
        >
          {big}
        </span>
      ) : null}
      <span
        className={cn(
          big
            ? cn('truncate font-semibold', tall ? 'text-[17px]' : 'text-sm')
            : cn('line-clamp-2 leading-tight font-extrabold', tall ? 'text-[28px]' : 'text-xl'),
        )}
      >
        {name}
      </span>
    </div>
  )
}

/** The dashed tear line between the halves. The notches are cut by the ticket's mask (see .ticket in index.css). */
function Perforation() {
  return <div aria-hidden className="mx-5 border-t-2 border-dashed border-line" />
}

interface TicketStubProps {
  benefit: Benefit
  selected: boolean
  index: number
  onSelect: () => void
}

/** A benefit in the ticket grid; selecting it opens its details. */
export function TicketStub({ benefit, selected, index, onSelect }: TicketStubProps) {
  return (
    <button
      type="button"
      id={`benefit-${benefit.id}`}
      aria-pressed={selected}
      aria-label={`${benefit.benefit_name || 'Untitled benefit'}, ${benefit.provider}. ${status(benefit)}.`}
      onClick={onSelect}
      style={{ '--notch-y': '134px', animationDelay: `${Math.min(index, 10) * 30}ms` } as CSSProperties}
      // The mask clips anything drawn outside the ticket, so the focus ring and the
      // selected outline are drawn just inside its edge instead.
      className="ticket glass group relative grid scroll-mt-24 animate-rise cursor-pointer overflow-hidden rounded-[20px] text-left transition-transform duration-150 outline-none hover:-translate-y-0.5"
    >
      <span
        aria-hidden
        className={cn(
          'pointer-events-none absolute inset-0 z-10 rounded-[20px] border-[3px]',
          selected ? 'border-primary' : 'hidden border-focus group-focus-visible:block',
        )}
      />
      <Band benefit={benefit} />
      <div className="grid gap-2 pt-2.5">
        <Perforation />
        <span className="flex items-center justify-between gap-2 px-4 pb-3.5 text-[13px] text-ink-muted">
          <span>{expiryLine(benefit)}</span>
          <span className="truncate">{capitalize(benefit.type)}</span>
        </span>
      </div>
    </button>
  )
}

interface TicketDetailProps {
  benefit: Benefit
  /** BenefitActions (or the edit form) for this benefit. */
  children: ReactNode
  className?: string
}

/** The selected benefit, as a big ticket with its details and every action. */
export function TicketDetail({ benefit, children, className }: TicketDetailProps) {
  const rows = [
    ['Expires', benefit.expiry_date ? formatDate(benefit.expiry_date) : 'No expiry'],
    [
      'Reminder',
      !benefit.expiry_date || benefit.needs_review
        ? null
        : benefit.reminder === 'off'
          ? 'None'
          : reminderLabel(benefit.reminder),
    ],
    ['Category', CATEGORIES[benefit.category]],
    ['Found in', benefit.source === 'imap' ? (benefit.source_account ?? 'Email') : SOURCES[benefit.source]],
    ['Value', benefit.points != null ? formatPoints(benefit.points, benefit.points_unit) : benefit.value],
  ].filter((r): r is [string, string] => Boolean(r[1]))

  return (
    <section
      aria-label={`${benefit.benefit_name || 'Untitled benefit'} details`}
      style={{ '--notch-y': '188px' } as CSSProperties}
      className={cn('ticket glass-float grid animate-rise overflow-hidden rounded-[26px]', className)}
    >
      <Band benefit={benefit} tall />
      <div className="grid gap-4 pt-3">
        <Perforation />
        <div className="grid gap-4 px-6 pb-6">
          <dl className="grid grid-cols-2 gap-3 text-sm">
            {rows.map(([label, value]) => (
              <div key={label} className="grid gap-0.5">
                <dt className="text-xs text-ink-muted">{label}</dt>
                <dd className="font-semibold [overflow-wrap:anywhere]">{value}</dd>
              </div>
            ))}
          </dl>
          {benefit.terms_summary ? <p className="text-sm text-ink-muted">{benefit.terms_summary}</p> : null}
          {benefit.source_link ? (
            <a
              href={benefit.source_link}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-h-11 items-center gap-1.5 justify-self-start text-sm font-semibold text-primary-text underline-offset-4 hover:underline"
            >
              <ExternalLink className="size-4" aria-hidden />
              Open the email<span className="sr-only"> for {benefit.benefit_name} (opens in a new tab)</span>
            </a>
          ) : null}
          {benefit.needs_review ? (
            <p className="flex flex-wrap items-center gap-2 rounded-xl bg-warn-soft px-3 py-2.5 text-sm text-warn">
              <TriangleAlert className="size-4 shrink-0" aria-hidden />
              <span className="font-semibold">Waiting for review.</span>
              <Link href="/#review" className="font-semibold underline underline-offset-4">
                Review it on the dashboard
              </Link>
            </p>
          ) : null}
          {children}
        </div>
      </div>
    </section>
  )
}
