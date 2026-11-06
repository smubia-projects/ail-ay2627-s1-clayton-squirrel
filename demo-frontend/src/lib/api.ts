// Typed client for the app's API. Benefit mirrors ExtractedBenefit in backend/app/extraction.py.
// AI Lodge demo: requests are answered in the browser by demo/server.ts, which keeps the
// benefit list in localStorage and forwards the AI features (extract, digest, ask) to the
// real backend/ API through lib/aiApi.ts.

import { SIGNED_OUT, demoRequest } from '../demo/server'

export type ExpiryConfidence = 'explicit' | 'computed' | 'ambiguous' | 'unknown'

export interface Benefit {
  id: string
  /**
   * email: pasted or uploaded on the Add benefits page (AI Lodge demo).
   * gmail: the sample inbox the demo starts with. Outlook / imap: the full app's inbox connections.
   * outlook: Outlook, Hotmail or Microsoft 365 (Connect Outlook).
   * imap: an email account read with an app password (Gmail, Yahoo, iCloud, ...). loyalty: a membership spotted from who emails
   * the user. manual: typed in on the All Benefits page.
   */
  source: 'email' | 'gmail' | 'outlook' | 'imap' | 'loyalty' | 'card' | 'manual'
  is_benefit: boolean
  benefit_name: string
  provider: string
  /** What kind of benefit it is (TYPES). */
  type: string
  /** What it's spent on (CATEGORIES). */
  category: string
  value: string | null
  /** A points/miles balance the user entered, shown instead of value. */
  points?: number | null
  /** Loyalty memberships: "points", "miles" or "Avios". */
  points_unit?: string
  /** When to email about it: null is 1 week before, "off" never, a number is days before expiry. */
  reminder?: number | 'off' | null
  expiry_date: string | null
  expiry_confidence: ExpiryConfidence
  expiry_reasoning: string
  terms_summary: string | null
  /** A voucher or promo code to use at checkout. */
  code?: string | null
  source_snippet: string
  /** Gmail benefits only: link to the email and its subject line. */
  source_link?: string
  source_label?: string | null
  /** IMAP benefits only: the address the email came from. */
  source_account?: string
  needs_review: boolean
  review_reason: string | null
  /** The date the user used it up (YYYY-MM-DD). */
  used_on?: string | null
  /** Card credits: dollars spent this period. */
  used_amount?: number | null
  /** Card credits: this period's dollar amount, worked out from value. Null for everything else. */
  credit_total: number | null
  days_until_expiry: number | null
}

/** One-tap changes from a benefit's card (see _quick_update in server.py). Undo sends the old values. */
export interface QuickChange {
  used?: boolean
  used_amount?: number
  points?: number | string | null
  reminder?: number | 'off' | null
}

export const TYPES = ['membership', 'subscription', 'voucher', 'other'] as const

export const CATEGORIES: Record<string, string> = {
  entertainment: 'Entertainment',
  transport: 'Transport',
  travel: 'Travel',
  dining: 'Dining',
  wellness: 'Wellness',
  shopping: 'Shopping',
  other: 'Others',
}

/** The fields a user can set when adding or editing (see _read_benefit_fields in server.py). */
export interface BenefitEdit {
  benefit_name: string
  provider: string
  type: string
  category: string
  value: string
  /** Whole number as typed; empty when the benefit has a value instead. */
  points: string
  expiry_date: string
  terms_summary: string
  code: string
}

/** Days before expiry a reminder can be sent (DAY_CHOICES in reminders.py). */
export const REMINDER_DAYS: Record<number, string> = {
  7: '1 week before',
  14: '2 weeks before',
  30: '1 month before',
  60: '2 months before',
  90: '3 months before',
  180: '6 months before',
  365: '1 year before',
}

/** A benefit's reminder when it hasn't chosen one (DEFAULT_DAYS in reminders.py). */
export const DEFAULT_REMINDER_DAYS = 7

export interface AskEntry {
  id: string
  question: string
  answer: string
  created_at: string
}

export interface RankedBenefit {
  benefit_name: string
  provider: string
  urgency_score: number
  reason: string
}

export interface Digest {
  ranked_benefits: RankedBenefit[]
  digest_text: string
}

/** One email for the AI to read: pasted text, or the raw source of an uploaded .eml file. */
export type EmailInput =
  | { text: string; received_date?: string | null; label?: string }
  | { eml: string; label?: string }

/** What reading one email found: the benefit added to the list, or null when it wasn't one. */
export interface ExtractResult {
  benefit: Benefit | null
  subject: string | null
}

export interface User {
  id: string
  email: string
  name: string | null
  has_password: boolean
  /** False until the user clicks the link emailed at sign-up; no reminders are sent until then. */
  email_verified: boolean
}

export interface GmailConnection {
  email: string
  connected_at: string
  last_sync_at: string | null
}

/** Connect Outlook: the same shape as a Gmail connection. */
export type OutlookConnection = GmailConnection

export interface Session {
  user: User | null
  google_enabled: boolean
  microsoft_enabled: boolean
  gmail: GmailConnection | null
  auto_scan: AutoScanStatus | null
}

/** The daily scan (auto_scan.py): on or off, and the scans it last started. */
export interface AutoScanStatus {
  enabled: boolean
  running: boolean
  added: number
  needs_review: number
  memberships: number
  /** Inboxes whose scan stopped with an error. */
  errors: number
}

export interface ScanStatus {
  state: 'idle' | 'running' | 'done' | 'error'
  checked?: number
  total?: number | null
  added?: number
  needs_review?: number
  skipped?: number
  /** Marketing emails skipped without the AI model. */
  filtered?: number
  failed?: number
  remaining?: number
  /** Every email within the scan limit has been read, but older matching ones exist. */
  limit_reached?: boolean
  /** Today's cap on emails read by the AI model is used up; the rest wait for tomorrow. */
  daily_limit_reached?: boolean
  /** Loyalty memberships newly found from who emails the user. */
  memberships?: number
  message?: string | null
}

export interface ImapAccount {
  id: string
  email: string
  host: string
  connected_at: string
  last_sync_at: string | null
  scan: ScanStatus
}

/** A benefit in Recently removed: restorable until delete_on. */
export interface RemovedBenefit extends Benefit {
  removed_at: string
  /** When the server deletes it for good (removed_at + 30 days). */
  delete_on: string
}

export interface CatalogCard {
  key: string
  name: string
  /** A code from the catalog's countries, e.g. "SG". */
  country: string
  needs_anniversary: boolean
  /** What the card always gives (rates, caps, fees): shown for reference, not tracked. */
  features: string[]
  /** What resets on a schedule; each becomes a tracked benefit. */
  perks: { name: string; value: string; resets: string }[]
}

export interface UserCard {
  id: string
  card_key: string
  name: string
  anniversary_month: number | null
}

export interface CardsResponse {
  cards: UserCard[]
  catalog: { checked: string; countries: { code: string; name: string }[]; cards: CatalogCard[] }
}

// Called when any request finds the session has ended, so the app can show
// the sign-in screen instead of a wall of errors.
let onUnauthorized: (() => void) | null = null
export const setUnauthorizedHandler = (fn: (() => void) | null) => {
  onUnauthorized = fn
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await demoRequest<T>(path, init)
  } catch (e) {
    if (e instanceof Error && e.message === SIGNED_OUT) onUnauthorized?.()
    throw e
  }
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const api = {
  session: () => request<Session>('/api/session'),
  /** Opens the demo profile (no account): its sample data on first visit. */
  startDemo: () => request<{ user: User }>('/api/demo/start', post({})),
  /** Reads one email with the AI model and adds what it finds (real API call). */
  extract: (email: EmailInput) => request<ExtractResult>('/api/extract', post(email)),
  register: (email: string, password: string, name: string) =>
    request<{ user: User }>('/api/auth/register', post({ email, password, name })),
  login: (email: string, password: string) => request<{ user: User }>('/api/auth/login', post({ email, password })),
  logout: () => request<{ ok: true }>('/api/auth/logout', post({})),
  /** Password for accounts that have one; otherwise the email address, typed out. */
  deleteAccount: (confirm: { password: string } | { email: string }) =>
    request<{ ok: true }>('/api/account/delete', post(confirm)),
  verifyEmail: (token: string) => request<{ user: User }>('/api/auth/verify-email', post({ token })),
  resendVerification: () => request<{ ok: true; email_enabled: boolean }>('/api/account/verification', post({})),
  changeEmail: (email: string) => request<{ user: User }>('/api/account/email', post({ email })),
  forgotPassword: (email: string) => request<{ ok: true; email_enabled: boolean }>('/api/auth/forgot', post({ email })),
  resetPassword: (token: string, password: string) =>
    request<{ user: User }>('/api/auth/reset', post({ token, password })),

  listBenefits: (signal?: AbortSignal) => request<Benefit[]>('/api/benefits', { signal }),
  approve: (id: string, expiryDate: string) =>
    request<Benefit>(`/api/benefits/${id}/approve`, post({ expiry_date: expiryDate })),
  dismiss: (id: string) => request<{ ok: true }>(`/api/benefits/${id}/dismiss`, post({})),
  removedBenefits: () => request<RemovedBenefit[]>('/api/benefits/removed'),
  restoreBenefit: (id: string) => request<Benefit>(`/api/benefits/${id}/restore`, post({})),
  createBenefit: (fields: BenefitEdit) => request<Benefit>('/api/benefits', post(fields)),
  updateBenefit: (id: string, changes: BenefitEdit) => request<Benefit>(`/api/benefits/${id}/update`, post(changes)),
  quickUpdate: (id: string, change: QuickChange) => request<Benefit>(`/api/benefits/${id}/quick`, post(change)),
  digest: () => request<Digest>('/api/digest'),
  ask: (question: string) => request<AskEntry>('/api/ask', post({ question })),
  askHistory: (signal?: AbortSignal) => request<AskEntry[]>('/api/ask/history', { signal }),
  clearAskHistory: () => request<{ ok: true }>('/api/ask/history/clear', post({})),

  gmailStatus: () => request<{ connection: GmailConnection | null; scan: ScanStatus }>('/api/gmail/status'),
  startScan: () => request<ScanStatus>('/api/gmail/scan', post({})),
  disconnectGmail: () => request<{ ok: true }>('/api/gmail/disconnect', post({})),

  outlookStatus: () => request<{ connection: OutlookConnection | null; scan: ScanStatus }>('/api/outlook/status'),
  scanOutlook: () => request<ScanStatus>('/api/outlook/scan', post({})),
  disconnectOutlook: () => request<{ ok: true; remove_access_url: string }>('/api/outlook/disconnect', post({})),

  autoScanStatus: () => request<AutoScanStatus>('/api/auto-scan'),
  setAutoScan: (enabled: boolean) => request<AutoScanStatus>('/api/auto-scan', post({ enabled })),
  imapAccounts: () => request<ImapAccount[]>('/api/imap'),
  connectImap: (email: string, password: string, host: string) =>
    request<ImapAccount>('/api/imap', post({ email, password, host })),
  scanImap: (id: string) => request<ScanStatus>(`/api/imap/${id}/scan`, post({})),
  removeImap: (id: string) => request<{ ok: true }>(`/api/imap/${id}/remove`, post({})),

  setTimezone: (timezone: string) => request<{ ok: true }>('/api/timezone', post({ timezone })),

  cards: () => request<CardsResponse>('/api/cards'),
  addCard: (cardKey: string, anniversaryMonth: number | null) =>
    request<UserCard>('/api/cards', post({ card_key: cardKey, anniversary_month: anniversaryMonth })),
  removeCard: (id: string) => request<{ ok: true }>(`/api/cards/${id}/remove`, post({})),
}

/** Full-page navigations (not fetch). Demo: they come straight back, handled by demo/server.ts. */
export const googleUrl = (purpose: 'login' | 'connect') =>
  purpose === 'login' ? '/?demo=google-login' : '/connections?demo=gmail-connect'
export const MICROSOFT_CONNECT_URL = '/connections?demo=outlook-connect'

export const errorMessage = (e: unknown) => (e instanceof Error ? e.message : 'Something went wrong.')
