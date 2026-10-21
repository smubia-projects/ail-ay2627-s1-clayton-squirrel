import { useState } from 'react'
import { AutoScanPanel } from '../components/AutoScanPanel'
import { CardsPanel } from '../components/CardsPanel'
import { EmailAccountsPanel } from '../components/EmailAccountsPanel'
import { GivenUpEmails } from '../components/GivenUpEmails'
import { GmailPanel } from '../components/GmailPanel'
import { OutlookPanel } from '../components/OutlookPanel'
import type { AutoScanStatus, Session } from '../lib/api'

interface ConnectionsPageProps {
  session: Session
  /** Reloads the benefit list after a scan or a card change. */
  onBenefitsChanged: () => void
  onSessionChange: () => void
  autoScan: AutoScanStatus | null
  onAutoScanChange: (status: AutoScanStatus) => void
}

/** Where benefits come from: email accounts and cards. */
export function ConnectionsPage({
  session,
  onBenefitsChanged,
  onSessionChange,
  autoScan,
  onAutoScanChange,
}: ConnectionsPageProps) {
  // Turning the daily scan on can start scans; remounting the inbox panels makes them show and follow those.
  const [panelsKey, setPanelsKey] = useState(0)

  function autoScanChanged(status: AutoScanStatus) {
    onAutoScanChange(status)
    if (status.running) setPanelsKey((k) => k + 1)
  }

  return (
    <div className="grid gap-6">
      <h1 tabIndex={-1} className="text-2xl font-bold tracking-tight outline-none sm:text-3xl">
        Connections
      </h1>
      <div className="grid items-start gap-6 lg:grid-cols-2">
        {/* Email sources stacked on the left, so a tall form doesn't leave a gap beside cards. */}
        <div key={panelsKey} className="grid items-start gap-6">
          <GmailPanel
            googleEnabled={session.google_enabled}
            connection={session.gmail}
            onConnectionChange={onSessionChange}
            onScanFinished={onBenefitsChanged}
          />
          <OutlookPanel microsoftEnabled={session.microsoft_enabled} onScanFinished={onBenefitsChanged} />
          <EmailAccountsPanel onScanFinished={onBenefitsChanged} />
          <GivenUpEmails />
        </div>
        <div className="grid items-start gap-6">
          {autoScan ? <AutoScanPanel status={autoScan} onChange={autoScanChanged} /> : null}
          <CardsPanel onChanged={onBenefitsChanged} />
        </div>
      </div>
    </div>
  )
}
