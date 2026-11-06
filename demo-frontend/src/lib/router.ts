import { useSyncExternalStore } from 'react'

// A tiny History API router: four pages don't need a routing library.
// vercel.json rewrites each of these paths to index.html.

export const PAGES = [
  { path: '/', label: 'Dashboard', short: 'Home' },
  { path: '/benefits', label: 'All Benefits', short: 'Benefits' },
  { path: '/assistant', label: 'Assistant', short: 'Assistant' },
  { path: '/add', label: 'Add benefits', short: 'Add' },
] as const

const listeners = new Set<() => void>()

function subscribe(listener: () => void) {
  listeners.add(listener)
  window.addEventListener('popstate', listener)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('popstate', listener)
  }
}

export function navigate(to: string) {
  if (to === window.location.pathname + window.location.search + window.location.hash) return
  window.history.pushState(null, '', to)
  listeners.forEach((l) => l())
}

/** The current pathname, without a trailing slash (except for "/"). */
export function usePath() {
  const path = useSyncExternalStore(subscribe, () => window.location.pathname)
  return path.length > 1 ? path.replace(/\/+$/, '') : path
}
