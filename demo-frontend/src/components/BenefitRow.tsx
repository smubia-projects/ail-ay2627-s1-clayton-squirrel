import { ExternalLink } from 'lucide-react'
import type { ReactNode } from 'react'
import { CATEGORIES, type Benefit } from '../lib/api'
import { cn } from '../lib/cn'
import { capitalize, formatDate, formatPoints, reminderLabel, urgency } from '../lib/format'
import { CategoryArt } from './CategoryArt'
import { UrgencyBadge } from './UrgencyBadge'

const METER_WINDOW_DAYS = 90
// Brighter than the text tones, as in the design, so the bars read in both themes.
const meterTone = { danger: 'bg-[#f87171]', warn: 'bg-[#f59e0b]', ok: 'bg-[#4ade80]', neutral: 'bg-line' }

/** One benefit as a list item. `children` (e.g. action buttons) render under the details. */
interface BenefitRowProps {
  benefit: Benefit
  /** Position in the list, for the staggered entrance (capped, so long lists don't wait). */
  index?: number
  /** The terms summary under the details; off for short lists like "Up next". */
  showTerms?: boolean
  children?: ReactNode
}

export function BenefitRow({ benefit, index = 0, showTerms = true, children }: BenefitRowProps) {
  const days = benefit.days_until_expiry
  const { tone } = urgency(days)
  const meta = [
    {
      card: 'Card perk',
      email: benefit.source_label ? `From “${benefit.source_label}”` : 'From an email you added',
      gmail: 'From Gmail',
      outlook: 'From Outlook',
      imap: `From ${benefit.source_account ?? 'email'}`,
      loyalty: 'Membership found in your email',
      manual: 'Added by you',
    }[benefit.source],
    benefit.provider,
    capitalize(benefit.type),
    // Skipped when it adds nothing ("Others", or the same word as the type, like Travel).
    !['other', benefit.type].includes(benefit.category) && CATEGORIES[benefit.category],
    benefit.points != null ? formatPoints(benefit.points, benefit.points_unit) : benefit.value,
    benefit.expiry_date && `Expires ${formatDate(benefit.expiry_date)}`,
    // Set from the ⋯ menu. Not for benefits under review: they aren't reminded until confirmed.
    benefit.expiry_date &&
      !benefit.needs_review &&
      (benefit.reminder === 'off' ? 'No reminder' : `Reminder ${reminderLabel(benefit.reminder).toLowerCase()}`),
  ].filter(Boolean)
  // A fuller bar means closer to expiry, across a 90-day window.
  const fill = days == null ? null : Math.max(4, Math.min(100, 100 - (Math.max(days, 0) / METER_WINDOW_DAYS) * 100))

  return (
    <li
      style={{ animationDelay: `${Math.min(index, 10) * 40}ms` }}
      className="grid animate-rise grid-cols-[auto_minmax(0,1fr)] items-center gap-x-4 gap-y-2 px-5 py-4 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:px-6 sm:py-5"
    >
      <CategoryArt
        category={benefit.category}
        className="row-span-2 size-12 self-start sm:row-span-1 sm:size-14 sm:self-center"
      />
      <div className="min-w-0">
        <p className="text-[17px] font-semibold">{benefit.benefit_name || 'Untitled benefit'}</p>
        <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-sm text-ink-muted">
          {meta.map((m, i) => (
            // Static per render and never reordered, so the index is a safe key.
            <span key={i}>{m}</span>
          ))}
        </p>
      </div>
      {/* Phones: under the name. Wider screens: on the right. */}
      <div className="justify-self-start sm:justify-self-end">
        {benefit.needs_review ? (
          <span className="rounded-full bg-warn-soft px-2.5 py-1 text-xs font-semibold whitespace-nowrap text-warn">
            Needs review
          </span>
        ) : (
          <UrgencyBadge days={days} />
        )}
      </div>
      {fill !== null && !benefit.needs_review ? (
        <div className="col-span-full h-1 overflow-hidden rounded-full bg-surface-2" aria-hidden>
          <div className={cn('h-full rounded-full', meterTone[tone])} style={{ width: `${fill}%` }} />
        </div>
      ) : null}
      {showTerms && benefit.terms_summary ? (
        <p className="col-span-full text-sm text-ink-muted">{benefit.terms_summary}</p>
      ) : null}
      {benefit.source_link ? (
        <a
          href={benefit.source_link}
          target="_blank"
          rel="noreferrer"
          className="col-span-full inline-flex min-h-11 items-center gap-1.5 justify-self-start text-sm font-semibold text-primary-text underline-offset-4 hover:underline"
        >
          <ExternalLink className="size-4" aria-hidden />
          Open the email<span className="sr-only"> for {benefit.benefit_name} (opens in a new tab)</span>
        </a>
      ) : null}
      {children ? <div className="col-span-full">{children}</div> : null}
    </li>
  )
}
