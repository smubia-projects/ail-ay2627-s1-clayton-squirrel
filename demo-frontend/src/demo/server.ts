// The demo's in-browser "server". It answers every /api request lib/api.ts
// makes and keeps the visitor's benefits in localStorage, starting from the
// sample data in data.json (captured from the full app by capture_demo_data.py).
//
// AI Lodge version (no accounts, no inbox connections):
// - "Try the demo" opens one demo profile, Alex's sample benefits on first visit.
//   "Reset demo data" puts it back.
// - The three AI features call the real backend/ API (lib/aiApi.ts):
//   /api/extract reads one pasted or uploaded email, /api/digest ranks the list,
//   /api/ask answers questions. The benefit list is sent along with each request;
//   the server stores nothing.
// - Everything else (edits, review queue, card perks, ask history) stays local.
// - The full app's Gmail/Outlook/IMAP/daily-scan routes below are still answered
//   with pretend scans but nothing in the demo UI calls them any more.

import type {
  AskEntry,
  AutoScanStatus,
  Benefit,
  BenefitEdit,
  CardsResponse,
  Digest,
  EmailInput,
  ExtractResult,
  GmailConnection,
  ImapAccount,
  QuickChange,
  RemovedBenefit,
  ScanStatus,
  User,
  UserCard,
} from '../lib/api'
import { aiPost } from '../lib/aiApi'
import { CATEGORIES, TYPES } from '../lib/api'
import captured from './data.json'

type Stored = Omit<Benefit, 'days_until_expiry' | 'credit_total'> & {
  /** Card benefits: the user card they came from. */
  card_id?: string
  /** Recently removed: when. */
  removed_at?: string | null
}

interface Job {
  started: number
  total: number
  /** Benefits this scan finds, added when it finishes. */
  finds: Stored[]
  finished: boolean
}

/** One demo account's data. */
interface Account {
  user: User
  benefits: Stored[]
  cards: UserCard[]
  ask: AskEntry[]
  gmail: GmailConnection | null
  outlook: GmailConnection | null
  imap: Omit<ImapAccount, 'scan'>[]
  autoScan: boolean
  /** Which sample finds each inbox has handed out already. */
  found: Record<string, number>
  jobs: Record<string, Job>
}

interface Store {
  version: number
  /** The signed-in account's key (its email in lower case), or null when signed out. */
  current: string | null
  accounts: Record<string, Account>
}

const VERSION = 5 // bump when data.json changes, so browsers drop the old saved copy
const STORAGE_KEY = 'squirrel-demo'
const EMAIL_EVERY_MS = 220 // how fast a pretend scan "reads" emails
const REMOVED_KEEP_DAYS = 30

// ---------------------------------------------------------------------------
// Dates: the sample data was captured on one day; move it to today.
// ---------------------------------------------------------------------------

const DAY_MS = 86_400_000
const localToday = () => {
  const d = new Date()
  return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
}
const isoDay = (d: Date) => d.toISOString().slice(0, 10)
const todayIso = () => isoDay(localToday())
const addDays = (iso: string, days: number) => isoDay(new Date(Date.parse(`${iso}T00:00:00Z`) + days * DAY_MS))
const nowIso = () => new Date().toISOString().replace(/\.\d+Z$/, '+00:00')
const SHIFT_DAYS = Math.round((localToday().getTime() - Date.parse(`${captured.captured_on}T00:00:00Z`)) / DAY_MS)

function shift<T>(value: T): T {
  if (typeof value === 'string') {
    if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return addDays(value, SHIFT_DAYS) as T
    if (/^\d{4}-\d{2}-\d{2}T/.test(value))
      return new Date(Date.parse(value) + SHIFT_DAYS * DAY_MS).toISOString().replace(/\.\d+Z$/, '+00:00') as T
    return value
  }
  if (Array.isArray(value)) return value.map(shift) as T
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(value)) out[k] = k === 'source_snippet' ? v : shift(v)
    return out as T
  }
  return value
}

const newId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(6)), (b) => b.toString(16).padStart(2, '0')).join('')

// ---------------------------------------------------------------------------
// Accounts, kept in localStorage so a refresh doesn't lose the visitor's changes.
// Each email has its own: the ones in data.json start from their own sample
// data, and any other email starts from the first one's.
// ---------------------------------------------------------------------------

type Captured = (typeof captured.accounts)[number]

function strip(b: Benefit): Stored {
  const { days_until_expiry: _d, credit_total: _c, ...rest } = b
  return rest
}

function fromCaptured(source: Captured, email: string): Account {
  const data = shift(source)
  const cards = data.cards as UserCard[]
  return {
    // A new id each time, so a reset gives a fresh dashboard.
    user: { ...(data.user as User), id: newId(), email, email_verified: true },
    benefits: (data.benefits as Benefit[]).map((b) => {
      // A card's perks are listed under the card's name.
      const cardId = b.source === 'card' ? cards.find((c) => c.name === b.provider)?.id : undefined
      // The sample inbox's benefits show as emails the visitor added (no Gmail links in the demo).
      const fromEmail = b.source === 'gmail' || b.source === 'outlook' || b.source === 'imap'
      const { source_link: _l, ...rest } = strip(b)
      return { ...rest, ...(fromEmail ? { source: 'email' as const } : {}), ...(cardId ? { card_id: cardId } : {}) }
    }),
    cards,
    ask: data.ask_history as AskEntry[],
    gmail: (data.gmail as GmailConnection | null) ?? null,
    outlook: null,
    imap: [],
    autoScan: false,
    found: {},
    jobs: {},
  }
}

const emptyStore = (): Store => ({ version: VERSION, current: null, accounts: {} })
/** Stands in for the signed-in account while no one is signed in. */
const placeholder = () => fromCaptured(captured.accounts[0], '')

function load(): Store {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as Store | null
    if (saved?.version === VERSION) return saved
  } catch {
    // Private window or blocked storage: start fresh.
  }
  return emptyStore()
}

let store = load()
/** The signed-in account. */
let state: Account = (store.current && store.accounts[store.current]) || placeholder()
const signedIn = () => store.current !== null && store.accounts[store.current] === state

function save() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    // Changes just won't survive a refresh.
  }
}

/** Puts every demo account back to its sample data and signs out. */
export function resetDemo() {
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Nothing saved.
  }
  store = emptyStore()
  state = placeholder()
}

// ---------------------------------------------------------------------------
// Benefits as the page sees them (server.py with_days and credit_total).
// ---------------------------------------------------------------------------

function creditTotal(b: Stored): number | null {
  if (b.source !== 'card') return null
  const value = b.value ?? ''
  const december = value.match(/\$(\d+(?:\.\d+)?) in December/)
  if (december && (b.expiry_date ?? '').slice(5, 7) === '12') return Number(december[1])
  const m = value.match(/\$(\d+(?:\.\d+)?)/)
  return m ? Number(m[1]) : null
}

function shown(b: Stored): Benefit {
  const { card_id: _c, removed_at: _r, ...rest } = b
  const days = b.expiry_date
    ? Math.round((Date.parse(`${b.expiry_date}T00:00:00Z`) - localToday().getTime()) / DAY_MS)
    : null
  return { ...rest, days_until_expiry: days, credit_total: creditTotal(b) }
}

const active = () => state.benefits.filter((b) => !b.removed_at)

function find(id: string): Stored {
  const b = state.benefits.find((x) => x.id === id && !x.removed_at)
  if (!b) throw new Error('That benefit no longer exists.')
  return b
}

function parsePoints(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const points = Number(String(value).replaceAll(',', '').trim())
  if (!Number.isInteger(points)) throw new Error('Enter points as a whole number, like 12500.')
  if (points < 0 || points > 10_000_000_000) throw new Error('Enter a points balance between 0 and 10 billion.')
  return points
}

function readFields(data: BenefitEdit) {
  const text = (v: string | undefined, limit: number, label: string) => {
    const t = (v ?? '').trim()
    if (t.length > limit) throw new Error(`Keep ${label} under ${limit} characters.`)
    return t || null
  }
  const name = text(data.benefit_name, 200, 'benefit name')
  if (!name) throw new Error('Give the benefit a name.')
  if (!(TYPES as readonly string[]).includes(data.type)) throw new Error('Pick a type from the list.')
  if (!(data.category in CATEGORIES)) throw new Error('Pick a category from the list.')
  const expiry = text(data.expiry_date, 10, 'expiry date')
  if (expiry && Number.isNaN(Date.parse(`${expiry}T00:00:00Z`))) throw new Error('Use a real date (YYYY-MM-DD).')
  return {
    benefit_name: name,
    provider: text(data.provider, 200, 'provider') ?? '',
    type: data.type,
    category: data.category,
    value: text(data.value, 100, 'value'),
    expiry_date: expiry,
    terms_summary: text(data.terms_summary, 500, 'terms summary'),
    code: text(data.code, 64, 'code'),
    points: parsePoints(data.points),
  }
}

// ---------------------------------------------------------------------------
// Pretend scans
// ---------------------------------------------------------------------------

function sample(
  name: string,
  provider: string,
  type: string,
  category: string,
  value: string,
  days: number | null,
  terms: string,
  subject: string,
  code: string | null = null,
): Stored {
  const review = days === null
  return {
    id: '',
    source: 'gmail',
    is_benefit: true,
    benefit_name: name,
    provider,
    type,
    category,
    value,
    expiry_date: days === null ? null : addDays(todayIso(), days),
    expiry_confidence: review ? 'ambiguous' : 'explicit',
    expiry_reasoning: review ? 'Says "while stocks last" with no date.' : 'The email gives an exact expiry date.',
    terms_summary: terms,
    code,
    source_snippet: '',
    source_label: subject,
    needs_review: review,
    review_reason: review ? 'expiry is ambiguous' : null,
  }
}

// What each inbox's first scan finds; later scans find nothing new.
const FINDS: Record<string, Stored[]> = {
  gmail: [
    sample(
      'Free pastry with any coffee',
      'Bluebird Bakery',
      'voucher',
      'dining',
      '1 free pastry',
      9,
      'In store only, one per visit.',
      'A little something for you',
      'BLUE-PASTRY',
    ),
    sample(
      '$20 off a $100 spend',
      'Harbourfront Mall',
      'voucher',
      'shopping',
      '$20 off',
      33,
      'Show the email at the concierge to collect the voucher.',
      'Your member reward is ready',
    ),
    sample(
      'Double points weekend',
      'Maple Grocery',
      'membership',
      'shopping',
      '2× points',
      null,
      'Shop online or in store; points post within 7 days.',
      'Double points are back',
    ),
  ],
  outlook: [
    sample(
      'Free cinema upgrade',
      'CineMax Theatres',
      'voucher',
      'entertainment',
      'Free IMAX upgrade',
      15,
      'One upgrade per booking; IMAX and 4DX only.',
      'Upgrade your next movie on us',
      'CMX-UPGRADE',
    ),
    sample(
      'First month free',
      'PeakFit Studios',
      'subscription',
      'wellness',
      '1 month free',
      24,
      'Cancel before the trial ends to avoid the $49 monthly fee.',
      'Your free month starts now',
    ),
  ],
  imap: [
    sample(
      '15% off your next order',
      'Orchard Florists',
      'voucher',
      'shopping',
      '15% off',
      18,
      'Online orders over $40.',
      'Thanks for your order!',
      'BLOOM15',
    ),
  ],
}

function startJob(key: string, inbox: 'gmail' | 'outlook' | 'imap', source: Stored['source'], account?: string) {
  const job = state.jobs[key]
  if (job && !job.finished) return
  const already = state.found[key] ?? 0
  const finds = FINDS[inbox].slice(already).map((b) => ({
    ...b,
    id: newId(),
    source,
    ...(account ? { source_account: account } : {}),
  }))
  state.found[key] = already + finds.length
  state.jobs[key] = { started: Date.now(), total: 14 + Math.floor(Math.random() * 10), finds, finished: false }
  save()
}

function jobStatus(key: string): ScanStatus {
  const job = state.jobs[key]
  if (!job) return { state: 'idle' }
  const checked = Math.min(job.total, Math.floor((Date.now() - job.started) / EMAIL_EVERY_MS))
  const done = checked >= job.total
  if (done && !job.finished) {
    job.finished = true
    state.benefits.push(...job.finds)
    const connection = key === 'gmail' ? state.gmail : key === 'outlook' ? state.outlook : null
    if (connection) connection.last_sync_at = nowIso()
    const imap = state.imap.find((a) => `imap:${a.id}` === key)
    if (imap) imap.last_sync_at = nowIso()
    save()
  }
  // Benefits appear as they're "read", spread over the scan.
  const shownFinds = done ? job.finds : job.finds.slice(0, Math.floor((checked / job.total) * job.finds.length))
  const review = shownFinds.filter((b) => b.needs_review).length
  const filtered = Math.floor(checked / 3)
  return {
    state: done ? 'done' : 'running',
    checked,
    total: job.total,
    added: shownFinds.length - review,
    needs_review: review,
    skipped: Math.max(0, checked - filtered - shownFinds.length),
    filtered,
    failed: 0,
    remaining: 0,
    limit_reached: false,
    daily_limit_reached: false,
    memberships: 0,
    message: null,
  }
}

function autoScanStatus(): AutoScanStatus {
  const keys = ['gmail', 'outlook', ...state.imap.map((a) => `imap:${a.id}`)]
  const statuses = keys.map(jobStatus)
  return {
    enabled: state.autoScan,
    running: statuses.some((s) => s.state === 'running'),
    added: statuses.reduce((n, s) => n + (s.added ?? 0), 0),
    needs_review: statuses.reduce((n, s) => n + (s.needs_review ?? 0), 0),
    memberships: 0,
    errors: 0,
  }
}

// ---------------------------------------------------------------------------
// AI features: the real backend/ API (extract, digest, ask)
// ---------------------------------------------------------------------------

/** The ExtractedBenefit fields the backend reads (backend/app/main.py BenefitIn). */
const AI_FIELDS = [
  'is_benefit',
  'benefit_name',
  'provider',
  'type',
  'category',
  'expiry_confidence',
  'expiry_reasoning',
  'source_snippet',
  'value',
  'expiry_date',
  'terms_summary',
  'code',
  'points',
  'reminder',
  'needs_review',
  'review_reason',
  'used_on',
  'used_amount',
] as const

/** The visitor's current benefits, as the AI sees them (the server keeps nothing). */
const aiBenefits = () =>
  active()
    .filter((b) => !b.used_on)
    .slice(0, 300)
    .map((b) => Object.fromEntries(AI_FIELDS.map((k) => [k, b[k] ?? null])))

type ExtractedRecord = Omit<Stored, 'id' | 'source'>

async function extract(input: EmailInput): Promise<ExtractResult> {
  signedInUser()
  const { label, ...email } = input
  const result = await aiPost<{ benefit: ExtractedRecord; subject: string | null }>('/api/extract', {
    ...email,
    today: todayIso(),
  })
  if (!result.benefit.is_benefit) return { benefit: null, subject: result.subject }
  const b: Stored = {
    ...result.benefit,
    id: newId(),
    source: 'email',
    source_label: result.subject || label || 'An email you added',
  }
  state.benefits.push(b)
  save()
  return { benefit: shown(b), subject: result.subject }
}

async function digest(): Promise<Digest> {
  signedInUser()
  return aiPost<Digest>('/api/digest', { benefits: aiBenefits(), today: todayIso() })
}

async function ask(question: string): Promise<AskEntry> {
  signedInUser()
  const q = question.trim()
  if (!q) throw new Error('Type a question first.')
  if (q.length > 500) throw new Error('Keep your question under 500 characters.')
  const { answer } = await aiPost<{ answer: string }>('/api/ask', {
    question: q,
    benefits: aiBenefits(),
    today: todayIso(),
  })
  const entry: AskEntry = { id: newId(), question: q, answer, created_at: nowIso() }
  state.ask = [entry, ...state.ask].slice(0, 50)
  save()
  return entry
}

// ---------------------------------------------------------------------------
// Requests
// ---------------------------------------------------------------------------

const ok = { ok: true } as const
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

const validEmail = (email: string) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)

/** Signs in to this email's account, making it the first time from its sample data (or the first account's). */
function signIn(email: string, name?: string): { user: User } {
  const address = email.trim()
  if (!validEmail(address)) throw new Error('Enter a valid email address.')
  const key = address.toLowerCase()
  if (!store.accounts[key]) {
    const source = captured.accounts.find((a) => a.email === key) ?? captured.accounts[0]
    store.accounts[key] = fromCaptured(source, address)
  }
  state = store.accounts[key]
  if (name?.trim()) state.user.name = name.trim()
  store.current = key
  save()
  return { user: state.user }
}

/** The error for requests made while signed out (a 401 from server.py). */
export const SIGNED_OUT = 'Sign in first.'

function signedInUser(): User {
  if (!signedIn()) throw new Error(SIGNED_OUT)
  return state.user
}

const cardsResponse = (): CardsResponse => ({
  cards: state.cards,
  catalog: captured.catalog as CardsResponse['catalog'],
})

function route(method: string, path: string, body: Record<string, unknown>): unknown {
  // Signed out
  if (path === '/api/session')
    return {
      user: signedIn() ? state.user : null,
      google_enabled: false,
      microsoft_enabled: false,
      gmail: null,
      auto_scan: null,
    }
  // "Try the demo": the demo profile (Alex's sample data the first time).
  if (path === '/api/demo/start') return signedIn() ? { user: state.user } : signIn(captured.accounts[0].email)
  if (path === '/api/auth/register') {
    if (String(body.password ?? '').length < 8) throw new Error('Use a password of at least 8 characters.')
    return signIn(String(body.email ?? ''), String(body.name ?? ''))
  }
  if (path === '/api/auth/login') {
    if (!body.password) throw new Error('Enter your password.')
    return signIn(String(body.email ?? ''))
  }
  if (path === '/api/auth/forgot') return { ok: true, email_enabled: false }
  if (path === '/api/auth/reset' || path === '/api/auth/verify-email')
    return signedIn() ? { user: state.user } : signIn(captured.accounts[0].email)

  const user = signedInUser()
  if (path === '/api/auth/logout') {
    store.current = null
    save()
    return ok
  }
  if (path === '/api/account/delete') {
    // Signing in with this email again starts it from its sample data.
    delete store.accounts[store.current!]
    store.current = null
    state = placeholder()
    save()
    return ok
  }
  if (path === '/api/account/verification') return { ok: true, email_enabled: false }
  if (path === '/api/account/email') {
    const email = String(body.email ?? '').trim()
    if (!validEmail(email)) throw new Error('Enter a valid email address.')
    const key = email.toLowerCase()
    if (key !== store.current && store.accounts[key]) throw new Error('Another account already uses that email.')
    delete store.accounts[store.current!]
    store.accounts[key] = state
    store.current = key
    user.email = email
    save()
    return { user }
  }
  if (path === '/api/timezone') return ok

  // Benefits
  if (path === '/api/benefits' && method === 'GET') return active().map(shown)
  if (path === '/api/benefits' && method === 'POST') {
    const fields = readFields(body as unknown as BenefitEdit)
    const b: Stored = {
      id: newId(),
      source: 'manual',
      is_benefit: true,
      ...fields,
      expiry_confidence: fields.expiry_date ? 'explicit' : 'unknown',
      expiry_reasoning: fields.expiry_date ? 'Added by you.' : 'Added by you, with no expiry.',
      source_snippet: '',
      needs_review: false,
      review_reason: null,
    }
    state.benefits.push(b)
    save()
    return shown(b)
  }
  if (path === '/api/benefits/removed') {
    const cutoff = Date.now() - REMOVED_KEEP_DAYS * DAY_MS
    state.benefits = state.benefits.filter((b) => !b.removed_at || Date.parse(b.removed_at) >= cutoff)
    return state.benefits
      .filter((b) => b.removed_at)
      .toSorted((a, b) => Date.parse(b.removed_at!) - Date.parse(a.removed_at!))
      .map((b): RemovedBenefit => ({
        ...shown(b),
        removed_at: b.removed_at!,
        delete_on: new Date(Date.parse(b.removed_at!) + REMOVED_KEEP_DAYS * DAY_MS).toISOString(),
      }))
  }
  let m = path.match(/^\/api\/benefits\/([0-9a-f]+)\/(approve|dismiss|restore|update|quick)$/)
  if (m) {
    const [, id, action] = m
    if (action === 'restore') {
      const b = state.benefits.find((x) => x.id === id && x.removed_at)
      if (!b) throw new Error('That benefit was deleted for good and can’t be restored.')
      b.removed_at = null
      save()
      return shown(b)
    }
    const b = find(id)
    if (action === 'dismiss') b.removed_at = nowIso()
    if (action === 'approve') {
      const expiry = String(body.expiry_date ?? '').trim() || null
      Object.assign(b, {
        expiry_date: expiry,
        expiry_confidence: expiry ? 'explicit' : 'unknown',
        expiry_reasoning: expiry ? 'Confirmed by you.' : 'You confirmed this benefit has no expiry.',
        needs_review: false,
        review_reason: null,
      })
    }
    if (action === 'update') {
      const fields = readFields(body as unknown as BenefitEdit)
      if (fields.expiry_date !== b.expiry_date)
        Object.assign(b, {
          expiry_confidence: fields.expiry_date ? 'explicit' : 'unknown',
          expiry_reasoning: fields.expiry_date ? 'Set by you.' : 'You removed the expiry date.',
        })
      Object.assign(b, fields, { needs_review: false, review_reason: null })
    }
    if (action === 'quick') {
      const change = body as QuickChange
      const total = creditTotal(b)
      if ('used' in change)
        Object.assign(
          b,
          change.used ? { used_on: todayIso(), used_amount: total } : { used_on: null, used_amount: null },
        )
      if ('used_amount' in change) {
        const amount = change.used_amount
        if (total == null) throw new Error('Only card credits have a balance to spend.')
        if (typeof amount !== 'number' || Number.isNaN(amount)) throw new Error('Enter an amount, like 12.50.')
        if (amount < 0 || amount > total) throw new Error(`Enter an amount between $0 and $${total}.`)
        const rounded = Math.round(amount * 100) / 100
        Object.assign(b, { used_amount: rounded || null, used_on: rounded >= total ? todayIso() : null })
      }
      if ('points' in change) b.points = parsePoints(change.points)
      if ('reminder' in change) b.reminder = change.reminder
    }
    save()
    return action === 'dismiss' ? ok : shown(b)
  }

  // Assistant (the questions themselves go to the real API: see aiRoute)
  if (path === '/api/ask/history') return state.ask
  if (path === '/api/ask/history/clear') {
    state.ask = []
    save()
    return ok
  }

  // Gmail and Outlook
  if (path === '/api/gmail/status') return { connection: state.gmail, scan: jobStatus('gmail') }
  if (path === '/api/gmail/scan') {
    if (!state.gmail) throw new Error('Connect Gmail first.')
    startJob('gmail', 'gmail', 'gmail')
    return jobStatus('gmail')
  }
  if (path === '/api/gmail/disconnect') {
    state.gmail = null
    delete state.jobs.gmail
    save()
    return ok
  }
  if (path === '/api/outlook/status') return { connection: state.outlook, scan: jobStatus('outlook') }
  if (path === '/api/outlook/scan') {
    if (!state.outlook) throw new Error('Connect Outlook first.')
    startJob('outlook', 'outlook', 'outlook')
    return jobStatus('outlook')
  }
  if (path === '/api/outlook/disconnect') {
    state.outlook = null
    delete state.jobs.outlook
    save()
    return { ok: true, remove_access_url: 'https://account.live.com/consent/Manage' }
  }

  // Daily scan and other email accounts
  if (path === '/api/auto-scan') {
    if (method === 'POST') {
      state.autoScan = Boolean(body.enabled)
      save()
    }
    return autoScanStatus()
  }
  if (path === '/api/imap' && method === 'GET')
    return state.imap.map((a) => ({ ...a, scan: jobStatus(`imap:${a.id}`) }))
  if (path === '/api/imap' && method === 'POST') {
    const email = String(body.email ?? '').trim()
    if (!validEmail(email)) throw new Error('Enter a valid email address.')
    if (!String(body.password ?? '').trim()) throw new Error('Enter the app password.')
    if (state.imap.some((a) => a.email.toLowerCase() === email.toLowerCase()))
      throw new Error('That account is already connected.')
    const account = {
      id: newId(),
      email,
      host: String(body.host ?? '') || `imap.${email.split('@')[1]}`,
      connected_at: nowIso(),
      last_sync_at: null,
    }
    state.imap.push(account)
    save()
    return { ...account, scan: jobStatus(`imap:${account.id}`) }
  }
  m = path.match(/^\/api\/imap\/([0-9a-f]+)\/(scan|remove)$/)
  if (m) {
    const account = state.imap.find((a) => a.id === m![1])
    if (!account) throw new Error('That account isn’t connected.')
    const key = `imap:${account.id}`
    if (m[2] === 'remove') {
      state.imap = state.imap.filter((a) => a !== account)
      delete state.jobs[key]
      save()
      return ok
    }
    startJob(key, 'imap', 'imap', account.email)
    return jobStatus(key)
  }

  // Credit cards
  if (path === '/api/cards' && method === 'GET') return cardsResponse()
  if (path === '/api/cards' && method === 'POST') {
    const key = String(body.card_key ?? '')
    const card = captured.catalog.cards.find((c) => c.key === key)
    if (!card) throw new Error('Pick a card from the list.')
    if (state.cards.some((c) => c.card_key === key)) throw new Error('You’ve already added that card.')
    const added: UserCard = {
      id: newId(),
      card_key: key,
      name: card.name,
      anniversary_month: typeof body.anniversary_month === 'number' ? body.anniversary_month : null,
    }
    state.cards.push(added)
    const perks = shift((captured.card_benefits as Record<string, Benefit[]>)[key] ?? [])
    state.benefits.push(...perks.map((b) => ({ ...strip(b), id: newId(), card_id: added.id })))
    save()
    return added
  }
  m = path.match(/^\/api\/cards\/([0-9a-f]+)\/remove$/)
  if (m) {
    const id = m[1]
    state.cards = state.cards.filter((c) => c.id !== id)
    state.benefits = state.benefits.filter((b) => b.card_id !== id)
    save()
    return ok
  }

  throw new Error('not found')
}

/** The requests answered by the real backend/ API, or null for the local ones. */
function aiRoute(path: string, body: Record<string, unknown>): Promise<unknown> | null {
  if (path === '/api/extract') return extract(body as unknown as EmailInput)
  if (path === '/api/digest') return digest()
  if (path === '/api/ask') return ask(String(body.question ?? ''))
  return null
}

/** Answers one request from lib/api.ts: AI features via the real API, the rest locally after a short pretend delay. */
export async function demoRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const body = typeof init.body === 'string' ? (JSON.parse(init.body) as Record<string, unknown>) : {}
  const url = new URL(path, window.location.origin)
  const ai = aiRoute(url.pathname, body)
  if (ai) return structuredClone(await ai) as T
  await sleep(80 + Math.random() * 120)
  if (init.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
  // A copy, so the page can't change the stored state by editing what it gets back.
  return structuredClone(route(method, url.pathname, body)) as T
}

// ---------------------------------------------------------------------------
// Google and Microsoft: the real app sends the browser to their sign-in pages.
// Here those links (googleUrl and MICROSOFT_CONNECT_URL in lib/api.ts) come
// straight back with ?demo=..., handled on page load.
// ---------------------------------------------------------------------------

/** A made-up address for the signed-in person, like sam.demo@gmail.com. */
const demoAddress = (domain: string) =>
  `${
    (state.user.name ?? '')
      .split(' ')[0]
      .toLowerCase()
      .replace(/[^a-z0-9]/g, '') || 'me'
  }.demo@${domain}`

function takeDemoRedirect() {
  const params = new URLSearchParams(window.location.search)
  const action = params.get('demo')
  if (!action) return
  params.delete('demo')
  let notice: string | null = null
  if (action === 'google-login') {
    signIn('alex.demo@gmail.com', 'Alex Demo')
    notice = 'signed_in'
  } else if (action === 'gmail-connect' && signedIn()) {
    state.gmail = { email: demoAddress('gmail.com'), connected_at: nowIso(), last_sync_at: null }
    notice = 'gmail_connected'
  } else if (action === 'outlook-connect' && signedIn()) {
    state.outlook = { email: demoAddress('outlook.com'), connected_at: nowIso(), last_sync_at: null }
    notice = 'outlook_connected'
  }
  save()
  if (notice) params.set('notice', notice)
  const query = params.toString()
  window.history.replaceState(null, '', window.location.pathname + (query ? `?${query}` : '') + window.location.hash)
}

takeDemoRedirect()
