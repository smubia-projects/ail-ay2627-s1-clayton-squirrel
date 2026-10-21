import { MailWarning } from 'lucide-react'
import { formatDate } from '../lib/format'

/** Shown while reminder emails to the user keep failing; the server tries again every 15 minutes. */
export function RemindersFailingBanner({ since }: { since: string }) {
  return (
    <section
      role="status"
      className="flex items-start gap-3 rounded-2xl border border-warn/30 bg-warn-soft px-4 py-3 sm:px-5"
    >
      <MailWarning className="mt-0.5 size-5 shrink-0 text-warn" aria-hidden />
      <p className="min-w-0 flex-1 text-sm">
        <strong>Reminder emails haven’t been getting through since {formatDate(since.slice(0, 10))}.</strong>{' '}
        <span className="text-ink-muted">
          Squirrel keeps trying every 15 minutes. Until they arrive, check what’s expiring soon here.
        </span>
      </p>
    </section>
  )
}
