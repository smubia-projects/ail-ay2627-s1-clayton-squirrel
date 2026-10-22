import { CardsPanel } from '../components/CardsPanel'
import { EmailImportPanel } from '../components/EmailImportPanel'
import type { Benefit } from '../lib/api'

interface AddPageProps {
  /** A benefit the AI found in an email. */
  onAdded: (benefit: Benefit) => void
  /** Reloads the benefit list after a card change. */
  onBenefitsChanged: () => void
}

/**
 * Where benefits come from in the AI Lodge demo: emails the visitor hands over
 * one at a time, and credit cards picked from a list. (The full app's Gmail,
 * Outlook, IMAP and daily-scan connections live on its Connections page.)
 */
export function AddPage({ onAdded, onBenefitsChanged }: AddPageProps) {
  return (
    <div className="grid gap-6">
      <h1 tabIndex={-1} className="text-2xl font-bold tracking-tight outline-none sm:text-3xl">
        Add benefits
      </h1>
      <div className="grid items-start gap-6 lg:grid-cols-2">
        <EmailImportPanel onAdded={onAdded} />
        <CardsPanel onChanged={onBenefitsChanged} />
      </div>
    </div>
  )
}
