// The real Squirrel API (backend/, on Cloud Run): the three AI features.
// Everything else in the demo is answered in the browser by demo/server.ts.
//
// The base URL is baked in at build time from VITE_API_BASE (set it in Vercel to
// the Cloud Run URL). The shared rate-limit engine's responses are surfaced as
// window events that components/QuotaModals.tsx turns into modals:
//  - 429 -> `squirrel:rate-limit` with detail.queries_used (the AI Lodge CTA)
//  - 503 -> `squirrel:demo-paused` with the body's message (demo paused notice)

export const API_BASE = (import.meta.env.VITE_API_BASE || 'http://localhost:8080').replace(/\/+$/, '')

export const RATE_LIMIT_EVENT = 'squirrel:rate-limit'
export const DEMO_PAUSED_EVENT = 'squirrel:demo-paused'

/** HTTP 429: this visitor used up the demo's AI requests. */
export class RateLimitError extends Error {
  readonly queriesUsed: number
  constructor(queriesUsed: number) {
    super('You’ve reached this demo’s limit for AI requests.')
    this.queriesUsed = queriesUsed
  }
}

/** HTTP 503 from the kill switch: the operators paused the demo. */
export class DemoPausedError extends Error {}

/** True for the two errors shown as modals, so pages don't also show an inline error. */
export const isQuotaError = (e: unknown) => e instanceof RateLimitError || e instanceof DemoPausedError

type Detail = { message?: string; queries_used?: number } | { msg?: string }[] | string | undefined

function detailMessage(detail: Detail, status: number): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return 'That request wasn’t valid. Try again with a shorter email.'
  return detail?.message || `The Squirrel AI service failed (HTTP ${status}).`
}

export async function aiPost<T>(path: string, body: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new Error('Couldn’t reach the Squirrel AI service. Check your connection and try again.')
  }

  let data: { detail?: Detail } & Record<string, unknown> = {}
  try {
    data = await response.json()
  } catch {
    // Non-JSON body: handled by the status checks below.
  }

  if (response.status === 429) {
    const detail = data.detail
    const used = detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail.queries_used ?? 0) : 0
    window.dispatchEvent(new CustomEvent(RATE_LIMIT_EVENT, { detail: { queriesUsed: used } }))
    throw new RateLimitError(used)
  }
  if (response.status === 503) {
    const message = detailMessage(data.detail, 503)
    window.dispatchEvent(new CustomEvent(DEMO_PAUSED_EVENT, { detail: { message } }))
    throw new DemoPausedError(message)
  }
  if (!response.ok) throw new Error(detailMessage(data.detail, response.status))
  return data as T
}
