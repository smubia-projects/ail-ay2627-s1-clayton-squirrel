import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { AcornRain } from './components/acorn/AcornRain'
import { CategoryArtSprite } from './components/CategoryArt'
import { Fireflies } from './components/Fireflies'
import { Header } from './components/Header'
import { Link } from './components/Link'
import { Woodland } from './components/Woodland'
import { useBenefits } from './hooks/useBenefits'
import { api, type AutoScanStatus, type Session, type User } from './lib/api'
import { RemindersFailingBanner } from './components/RemindersFailingBanner'
import { SCAN_POLL_MS } from './components/ScanStatus'
import { VerifyEmailBanner } from './components/VerifyEmailBanner'
import { PAGES, navigate, usePath } from './lib/router'
import { useToast } from './lib/toast'
import { AssistantPage } from './pages/AssistantPage'
import { BenefitsPage } from './pages/BenefitsPage'
import { ConnectionsPage } from './pages/ConnectionsPage'
import { DashboardPage } from './pages/DashboardPage'

const NOTICES: Record<string, string> = {
  gmail_connected: 'Gmail connected. Scan your inbox to find benefits.',
  outlook_connected: 'Outlook connected. Scan your mailbox to find benefits.',
  signed_in: 'Signed in with Google.',
  password_removed:
    'Signed in with Google. For your security, the password on this account was removed: sign in with Google, or use “Forgot password” to set a new one.',
}

interface AppProps {
  user: User
  session: Session
  notice: string | null
  /** Why connecting Gmail or Outlook failed, from the redirect back. */
  authError: string | null
  onSessionChange: () => void
  onSignOut: () => Promise<void>
  /** The account was deleted (its session is already gone). */
  onAccountDeleted: () => void
}

export default function App({
  user,
  session,
  notice,
  authError,
  onSessionChange,
  onSignOut,
  onAccountDeleted,
}: AppProps) {
  const toast = useToast()
  // Loaded once here so every page shares the same list and sees each other's edits.
  const { benefits, error, reload, upsert, remove } = useBenefits()
  const path = usePath()
  const page = PAGES.find((p) => p.path === path)

  // The daily scan starts on the server when the app loads (or when it's turned on); follow it here,
  // so the benefit list refreshes whichever page is open.
  const [autoScan, setAutoScan] = useState<AutoScanStatus | null>(session.auto_scan)
  useEffect(() => setAutoScan(session.auto_scan), [session.auto_scan])
  const autoScanFinished = useEffectEvent((s: AutoScanStatus) => {
    reload()
    const found = s.added + s.needs_review
    if (found)
      toast('success', `Daily scan found ${found} new benefit${found === 1 ? '' : 's'}.`, {
        label: s.needs_review ? 'Review' : 'See them',
        onClick: () => navigate(s.needs_review ? '/#review' : '/benefits'),
      })
    else if (s.memberships) toast('success', 'Daily scan found loyalty memberships to confirm in the review queue.')
    if (s.errors) toast('error', 'The daily scan couldn’t finish every inbox. See Connections for details.')
  })
  const autoScanRunning = autoScan?.running ?? false
  useEffect(() => {
    if (!autoScanRunning) return
    const id = window.setInterval(async () => {
      try {
        const s = await api.autoScanStatus()
        setAutoScan(s)
        if (!s.running) autoScanFinished(s)
      } catch {
        // Try again at the next tick; the inbox panels show their own errors.
      }
    }, SCAN_POLL_MS)
    return () => window.clearInterval(id)
  }, [autoScanRunning])

  // One-off message after returning from Google or Microsoft (the ref stops StrictMode showing it twice).
  const noticeShown = useRef(false)
  useEffect(() => {
    if (noticeShown.current) return
    if (authError) toast('error', authError)
    else if (notice && NOTICES[notice]) toast('success', NOTICES[notice])
    else return
    noticeShown.current = true
  }, [notice, authError, toast])

  // On each page change: new tab title, back to the top, and focus on the
  // page heading so screen readers announce the new page.
  const firstRender = useRef(true)
  useEffect(() => {
    document.title = page && page.path !== '/' ? `${page.label} · Squirrel` : 'Squirrel'
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    // A link like "/#review" goes to that section; any other page change starts at the top.
    const section = window.location.hash ? document.getElementById(window.location.hash.slice(1)) : null
    if (section) {
      section.scrollIntoView()
      return
    }
    window.scrollTo(0, 0)
    document.querySelector<HTMLElement>('main h1')?.focus({ preventScroll: true })
  }, [page])

  return (
    <>
      <CategoryArtSprite />
      <Woodland />
      <Fireflies />
      <AcornRain />
      <a
        href="#main"
        className="sr-only z-50 rounded-lg bg-surface px-4 py-2 font-semibold focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
      >
        Skip to main content
      </a>
      <Header path={path} user={user} onSignOut={onSignOut} onAccountDeleted={onAccountDeleted} />

      <main id="main" className="mx-auto grid max-w-6xl gap-6 px-4 pt-8 pb-16 sm:px-6 lg:px-8">
        {!user.email_verified ? <VerifyEmailBanner user={user} onUserChange={onSessionChange} /> : null}
        {session.reminders_failing_since ? <RemindersFailingBanner since={session.reminders_failing_since} /> : null}
        {path === '/benefits' ? (
          <BenefitsPage benefits={benefits} error={error} onRetry={reload} onUpdated={upsert} onRemoved={remove} />
        ) : path === '/assistant' ? (
          <AssistantPage benefits={benefits} />
        ) : path === '/connections' ? (
          <ConnectionsPage
            session={session}
            onBenefitsChanged={reload}
            onSessionChange={onSessionChange}
            autoScan={autoScan}
            onAutoScanChange={setAutoScan}
          />
        ) : path === '/' ? (
          <DashboardPage
            user={user}
            benefits={benefits}
            error={error}
            onRetry={reload}
            onConfirmed={upsert}
            onDismissed={remove}
          />
        ) : (
          <div className="grid justify-items-start gap-3 py-10">
            <h1 tabIndex={-1} className="text-2xl font-bold tracking-tight outline-none">
              Page not found
            </h1>
            <Link href="/" className="font-semibold text-primary-text underline-offset-4 hover:underline">
              Go to the dashboard
            </Link>
          </div>
        )}

        <footer className="pt-2 text-center text-sm text-ink-muted">
          Email benefits are read by an AI model (OpenAI); card perks come from a perk list. Dates the AI isn’t sure of
          always go to the review queue.
        </footer>
      </main>
    </>
  )
}
