import { useEffect, useRef } from 'react'
import { AcornRain } from './components/acorn/AcornRain'
import { CategoryArtSprite } from './components/CategoryArt'
import { Fireflies } from './components/Fireflies'
import { Header } from './components/Header'
import { Link } from './components/Link'
import { Woodland } from './components/Woodland'
import { useBenefits } from './hooks/useBenefits'
import type { User } from './lib/api'
import { PAGES, usePath } from './lib/router'
import { AddPage } from './pages/AddPage'
import { AssistantPage } from './pages/AssistantPage'
import { BenefitsPage } from './pages/BenefitsPage'
import { DashboardPage } from './pages/DashboardPage'

interface AppProps {
  user: User
  /** Back to the intro page. */
  onSignOut: () => Promise<void>
  /** Back to the sample data. */
  onReset: () => Promise<void>
}

export default function App({ user, onSignOut, onReset }: AppProps) {
  // Loaded once here so every page shares the same list and sees each other's edits.
  const { benefits, error, reload, upsert, remove } = useBenefits()
  const path = usePath()
  const page = PAGES.find((p) => p.path === path)

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
      <Header path={path} user={user} onSignOut={onSignOut} onReset={onReset} />

      <main id="main" className="mx-auto grid max-w-6xl gap-6 px-4 pt-8 pb-16 sm:px-6 lg:px-8">
        {path === '/benefits' ? (
          <BenefitsPage benefits={benefits} error={error} onRetry={reload} onUpdated={upsert} onRemoved={remove} />
        ) : path === '/assistant' ? (
          <AssistantPage benefits={benefits} />
        ) : path === '/add' ? (
          <AddPage onAdded={upsert} onBenefitsChanged={reload} />
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
          Emails are read by an AI model (via OpenRouter); card perks come from a perk list. Dates the AI isn’t sure of
          always go to the review queue. Your benefits stay in this browser.
        </footer>
      </main>
    </>
  )
}
