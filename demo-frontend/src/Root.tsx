import { LoaderCircle, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import App from './App'
import { Landing } from './components/landing/Landing'
import { Button } from './components/ui/Button'
import { Message } from './components/ui/Message'
import { api, errorMessage, setUnauthorizedHandler, type Session } from './lib/api'

/**
 * Loads the session and shows either the intro page or the dashboard.
 * AI Lodge demo: there are no accounts. "Try the demo" opens a demo profile
 * whose benefits live in this browser (see demo/server.ts).
 */
export function Root() {
  const [session, setSession] = useState<Session | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchSession = useCallback(() => {
    api.session().then(
      (s) => {
        setSession(s)
        setError(null)
      },
      (e) => setError(errorMessage(e)),
    )
  }, [])
  const load = useCallback(() => {
    setError(null)
    fetchSession()
  }, [fetchSession])

  useEffect(() => {
    fetchSession()
    setUnauthorizedHandler(() => setSession((s) => s && { ...s, user: null, gmail: null }))
    return () => setUnauthorizedHandler(null)
  }, [fetchSession])

  const leave = () => {
    window.history.replaceState(null, '', '/')
    setSession((s) => s && { ...s, user: null, gmail: null })
  }

  if (error) {
    return (
      <main className="mx-auto grid min-h-dvh max-w-md content-center gap-3 px-4">
        <Message tone="error">{error}</Message>
        <div>
          <Button icon={<RefreshCw className="size-4" aria-hidden />} onClick={load}>
            Try again
          </Button>
        </div>
      </main>
    )
  }

  if (!session) {
    return (
      <main className="grid min-h-dvh place-items-center" aria-busy="true">
        <LoaderCircle className="size-6 animate-spin text-ink-muted" aria-label="Loading" />
      </main>
    )
  }

  if (!session.user) {
    return (
      <Landing
        onStart={async () => {
          await api.startDemo()
          load()
        }}
      />
    )
  }

  return (
    <App
      // A reset gets a fresh dashboard, not the last one's state.
      key={session.user.id}
      user={session.user}
      onSignOut={async () => {
        try {
          await api.logout()
        } finally {
          leave()
        }
      }}
      onReset={async () => {
        await api.deleteAccount({ email: session.user?.email ?? '' })
        await api.startDemo()
        load()
      }}
    />
  )
}
