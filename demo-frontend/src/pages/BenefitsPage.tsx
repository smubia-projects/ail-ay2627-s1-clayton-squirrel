import { ChevronDown, CircleCheck, Inbox, ListFilter, Plus, RefreshCw, RotateCcw, ScanLine, Search } from 'lucide-react'
import { Fragment, useMemo, useRef, useState } from 'react'
import { BenefitActions } from '../components/BenefitActions'
import { TicketDetail, TicketStub } from '../components/BenefitTicket'
import { EditBenefitForm } from '../components/EditBenefitForm'
import { RecentlyRemoved } from '../components/RecentlyRemoved'
import { ScanCodeDialog } from '../components/ScanCodeDialog'
import { Link } from '../components/Link'
import { Button } from '../components/ui/Button'
import { Card, CardHeader, CountChip } from '../components/ui/Card'
import { Message } from '../components/ui/Message'
import { Skeleton } from '../components/ui/Skeleton'
import { useKeyboardShortcuts } from '../hooks/useKeyboardShortcuts'
import { useMediaQuery } from '../hooks/useMediaQuery'
import { api, CATEGORIES, errorMessage, TYPES, type Benefit } from '../lib/api'
import { cn } from '../lib/cn'
import { capitalize, formatDate } from '../lib/format'
import { fieldClass } from '../lib/styles'
import { useToast } from '../lib/toast'
import { isArchived, usageKind } from '../lib/usage'

const STATUSES = {
  all: 'Any status',
  soon: 'Expiring in 30 days',
  later: 'Expiring later',
  none: 'No expiry',
  expired: 'Expired',
  review: 'Needs review',
} as const
type Status = keyof typeof STATUSES

/** The chips above the tickets: quick filters by what kind of benefit it is. */
const KINDS = {
  all: 'All',
  voucher: 'Vouchers',
  credit: 'Card credits',
  points: 'Points',
  membership: 'Memberships',
  subscription: 'Subscriptions',
  review: 'To review',
} as const
type Kind = keyof typeof KINDS

function matchesKind(b: Benefit, kind: Kind) {
  if (kind === 'all') return true
  if (kind === 'review') return b.needs_review
  if (kind === 'voucher') return b.type === 'voucher'
  if (kind === 'credit' || kind === 'points') return usageKind(b) === kind
  return b.type === kind && usageKind(b) !== 'points'
}

const SORTS = { expiry: 'Expiry, soonest first', name: 'Name, A to Z', provider: 'Provider, A to Z' } as const
type Sort = keyof typeof SORTS

interface Filters {
  query: string
  kind: Kind
  type: string
  category: string
  source: string
  status: Status
  sort: Sort
}

const NO_FILTERS: Filters = {
  query: '',
  kind: 'all',
  type: 'all',
  category: 'all',
  source: 'all',
  status: 'all',
  sort: 'expiry',
}

function matchesStatus(b: Benefit, status: Status) {
  const days = b.days_until_expiry
  switch (status) {
    case 'all':
      return true
    case 'review':
      return b.needs_review
    case 'soon':
      return !b.needs_review && days != null && days >= 0 && days <= 30
    case 'later':
      return !b.needs_review && days != null && days > 30
    case 'none':
      return !b.needs_review && days == null
    case 'expired':
      return !b.needs_review && days != null && days < 0
  }
}

/** Filters from the address: the dashboard's tiles link to ?status=soon and ?kind=credit. */
function filtersFromUrl(): Filters {
  const params = new URLSearchParams(window.location.search)
  const status = params.get('status')
  const kind = params.get('kind')
  return {
    ...NO_FILTERS,
    status: status && status in STATUSES ? (status as Status) : 'all',
    kind: kind && kind in KINDS ? (kind as Kind) : 'all',
  }
}

function applyFilters(benefits: Benefit[], f: Filters) {
  const words = f.query.toLowerCase().split(/\s+/).filter(Boolean)
  const byName = (a: string, b: string) => a.localeCompare(b, undefined, { sensitivity: 'base' })
  return benefits
    .filter((b) => {
      if (f.type !== 'all' && b.type !== f.type) return false
      if (f.category !== 'all' && b.category !== f.category) return false
      if (f.source !== 'all' && b.source !== f.source) return false
      if (!matchesStatus(b, f.status)) return false
      if (!matchesKind(b, f.kind)) return false
      const text = [b.benefit_name, b.provider, b.value, b.terms_summary, b.source_label].join(' ').toLowerCase()
      return words.every((w) => text.includes(w))
    })
    .toSorted((a, b) => {
      if (f.sort === 'name') return byName(a.benefit_name, b.benefit_name)
      if (f.sort === 'provider') return byName(a.provider, b.provider) || byName(a.benefit_name, b.benefit_name)
      return (a.days_until_expiry ?? Infinity) - (b.days_until_expiry ?? Infinity)
    })
}

interface BenefitsPageProps {
  benefits: Benefit[] | null
  error: string | null
  onRetry: () => void
  onUpdated: (benefit: Benefit) => void
  onRemoved: (id: string) => void
}

export function BenefitsPage({ benefits, error, onRetry, onUpdated, onRemoved }: BenefitsPageProps) {
  const toast = useToast()
  const [filters, setFilters] = useState<Filters>(filtersFromUrl)
  const [editing, setEditing] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  // A code from the scanner, filled in on the Add form ('' when there's none to fill in).
  const [addCode, setAddCode] = useState('')
  const [scanning, setScanning] = useState(false)
  const scanButtonRef = useRef<HTMLButtonElement>(null)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const addButtonRef = useRef<HTMLButtonElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  // Wide screens: the selected ticket opens in a panel beside the grid. Phones: right under its ticket.
  const wide = useMediaQuery('(min-width: 1024px)')
  // A link like /benefits#benefit-<id> (from the Assistant) opens that benefit.
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    window.location.hash.startsWith('#benefit-') ? window.location.hash.slice('#benefit-'.length) : null,
  )

  useKeyboardShortcuts({
    '/': () => searchRef.current?.focus(),
  })

  // Used-up benefits leave the main list for the Used section; the same filters apply to both.
  const current = useMemo(() => benefits?.filter((b) => !isArchived(b)) ?? null, [benefits])
  const used = useMemo(() => benefits?.filter(isArchived) ?? [], [benefits])
  const shown = useMemo(() => (current ? applyFilters(current, filters) : null), [current, filters])
  const usedShown = useMemo(() => applyFilters(used, filters), [used, filters])
  const [usedOpen, setUsedOpen] = useState(false)
  // How many each chip would show, with the other filters as they are.
  const kindCounts = useMemo(
    () =>
      Object.fromEntries(
        (Object.keys(KINDS) as Kind[]).map((k) => [
          k,
          current ? applyFilters(current, { ...filters, kind: k }).length : 0,
        ]),
      ) as Record<Kind, number>,
    [current, filters],
  )

  // The open ticket: the one picked, else (on wide screens) the first. One that's used up or filtered out closes.
  const selected = shown?.find((b) => b.id === selectedId) ?? (wide ? (shown?.[0] ?? null) : null)

  async function restore(b: Benefit) {
    try {
      onUpdated(await api.quickUpdate(b.id, { used: false }))
      toast('success', `Moved “${b.benefit_name}” back to your benefits.`)
    } catch (e) {
      toast('error', `Couldn’t restore it: ${errorMessage(e)}`)
    }
  }
  // The chips and search are always in view; this counts the rest, in the "More filters" panel.
  const activeFilters = Object.entries(filters).filter(
    ([k, v]) => !['sort', 'query', 'kind'].includes(k) && v !== NO_FILTERS[k as keyof Filters],
  ).length
  const filtered = activeFilters > 0 || filters.query !== '' || filters.kind !== 'all'

  const set =
    <K extends keyof Filters>(key: K) =>
    (e: { target: { value: string } }) =>
      setFilters((f) => ({ ...f, [key]: e.target.value as Filters[K] }))

  const selectClass = cn(fieldClass, 'border-line')

  /** The open benefit's details and actions (or its edit form). */
  const detail = (b: Benefit, className?: string) => (
    <TicketDetail key={b.id} benefit={b} className={className}>
      {editing === b.id ? (
        <EditBenefitForm
          as="div"
          benefit={b}
          onCancel={() => setEditing(null)}
          onSaved={(saved) => {
            onUpdated(saved)
            setEditing(null)
            toast('success', `Saved “${saved.benefit_name}”.`)
          }}
        />
      ) : (
        <BenefitActions benefit={b} onEdit={() => setEditing(b.id)} onUpdated={onUpdated} onRemoved={onRemoved} />
      )}
    </TicketDetail>
  )

  return (
    <div className="grid gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1
            tabIndex={-1}
            className="text-3xl font-extrabold tracking-[-0.03em] outline-none sm:text-[40px] sm:leading-tight"
          >
            All Benefits
          </h1>
          {current ? (
            <p className="text-ink-muted">
              {current.length} saved
              {used.length ? ` · ${used.length} used` : ''}
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            ref={scanButtonRef}
            icon={<ScanLine className="size-4" aria-hidden />}
            onClick={() => setScanning(true)}
            disabled={!benefits}
          >
            Scan a code
          </Button>
          {!adding ? (
            <Button
              ref={addButtonRef}
              variant="primary"
              icon={<Plus className="size-4" aria-hidden />}
              onClick={() => {
                setAddCode('')
                setAdding(true)
              }}
            >
              Add a benefit
            </Button>
          ) : null}
        </div>
      </div>

      {scanning && benefits ? (
        <ScanCodeDialog
          benefits={benefits}
          onClose={() => {
            setScanning(false)
            requestAnimationFrame(() => scanButtonRef.current?.focus())
          }}
          onShow={(b) => {
            // Clear the filters so the benefit is in the list, then open it.
            setFilters(NO_FILTERS)
            setSelectedId(b.id)
            requestAnimationFrame(() =>
              document.getElementById(`benefit-${b.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }),
            )
          }}
          onAdd={(code) => {
            setAddCode(code)
            setAdding(true)
          }}
        />
      ) : null}

      {adding ? (
        <Card as="section" aria-labelledby="add-title">
          <CardHeader icon={Plus} title="Add a benefit" titleId="add-title" />
          <p className="px-5 pt-4 text-sm text-ink-muted">
            For vouchers, memberships and points that aren’t in your email, like a paper gift card or your hotel points
            balance.
          </p>
          <EditBenefitForm
            // A new code from the scanner starts a fresh form.
            key={addCode}
            as="div"
            initialCode={addCode}
            onCancel={() => {
              setAdding(false)
              requestAnimationFrame(() => addButtonRef.current?.focus())
            }}
            onSaved={(saved) => {
              onUpdated(saved)
              setAdding(false)
              setSelectedId(saved.id)
              requestAnimationFrame(() => addButtonRef.current?.focus())
              toast('success', `Added “${saved.benefit_name}”.`)
            }}
          />
        </Card>
      ) : null}

      <section aria-labelledby="filters-title" className="grid gap-3">
        <h2 id="filters-title" className="sr-only">
          Search and filter
        </h2>
        <div className="flex flex-wrap gap-2.5">
          <div className="relative min-w-60 flex-1">
            <label htmlFor="benefit-search" className="sr-only">
              Search benefits
            </label>
            <Search
              className="pointer-events-none absolute top-1/2 left-3.5 size-5 -translate-y-1/2 text-ink-muted"
              aria-hidden
            />
            <input
              id="benefit-search"
              ref={searchRef}
              type="search"
              value={filters.query}
              onChange={set('query')}
              placeholder="Search coffee, rides, points…"
              autoComplete="off"
              className={cn(fieldClass, 'glass min-h-12 rounded-2xl border-line pl-11')}
            />
            <kbd className="pointer-events-none absolute top-1/2 right-3 hidden -translate-y-1/2 rounded-md border border-line bg-surface-2 px-1.5 py-0.5 font-sans text-xs font-semibold text-ink-muted sm:block">
              /
            </kbd>
          </div>
          <button
            type="button"
            aria-expanded={filtersOpen}
            aria-controls="filters-panel"
            onClick={() => setFiltersOpen((open) => !open)}
            className="glass flex min-h-12 cursor-pointer items-center gap-2 rounded-2xl px-4 text-sm font-semibold transition-colors duration-150 hover:bg-surface-2"
          >
            <ListFilter className="size-5 text-ink-muted" aria-hidden />
            More filters
            {activeFilters ? <CountChip>{activeFilters} on</CountChip> : null}
            <ChevronDown
              className={cn('size-4 text-ink-muted transition-transform duration-200', filtersOpen && 'rotate-180')}
              aria-hidden
            />
          </button>
        </div>

        <div role="group" aria-label="Kind of benefit" className="flex flex-wrap gap-2">
          {(Object.keys(KINDS) as Kind[]).map((k) => {
            const on = filters.kind === k
            // Empty chips are left out, except the one that's on and All.
            if (!on && k !== 'all' && kindCounts[k] === 0) return null
            return (
              <button
                key={k}
                type="button"
                aria-pressed={on}
                onClick={() => setFilters((f) => ({ ...f, kind: k }))}
                className={cn(
                  'min-h-10 cursor-pointer rounded-full border px-4 text-sm font-semibold transition-colors duration-150',
                  on ? 'border-transparent bg-ink text-bg' : 'glass border-line hover:bg-surface-2',
                )}
              >
                {KINDS[k]}{' '}
                <span className={cn('tabular-nums', on ? 'opacity-70' : 'text-ink-muted')}>{kindCounts[k]}</span>
              </button>
            )
          })}
        </div>

        <Card id="filters-panel" hidden={!filtersOpen} className="grid gap-4 p-5 sm:grid-cols-2 lg:grid-cols-5">
          <div className="grid gap-1.5">
            <label htmlFor="filter-type" className="text-sm font-semibold">
              Type
            </label>
            <select id="filter-type" value={filters.type} onChange={set('type')} className={selectClass}>
              <option value="all">All types</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {capitalize(t)}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-1.5">
            <label htmlFor="filter-category" className="text-sm font-semibold">
              Category
            </label>
            <select id="filter-category" value={filters.category} onChange={set('category')} className={selectClass}>
              <option value="all">All categories</option>
              {Object.entries(CATEGORIES).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-1.5">
            <label htmlFor="filter-source" className="text-sm font-semibold">
              Source
            </label>
            <select id="filter-source" value={filters.source} onChange={set('source')} className={selectClass}>
              <option value="all">All sources</option>
              <option value="email">From emails</option>
              <option value="loyalty">Memberships found</option>
              <option value="card">Card perks</option>
              <option value="manual">Added by you</option>
            </select>
          </div>
          <div className="grid gap-1.5">
            <label htmlFor="filter-status" className="text-sm font-semibold">
              Status
            </label>
            <select id="filter-status" value={filters.status} onChange={set('status')} className={selectClass}>
              {Object.entries(STATUSES).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
          <div className="grid gap-1.5">
            <label htmlFor="filter-sort" className="text-sm font-semibold">
              Sort by
            </label>
            <select id="filter-sort" value={filters.sort} onChange={set('sort')} className={selectClass}>
              {Object.entries(SORTS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </div>
        </Card>
      </section>

      <section aria-labelledby="list-title" className="grid gap-4">
        <div className="flex items-center justify-between gap-3">
          <h2 id="list-title" className="text-lg font-semibold tracking-tight">
            Your benefits
          </h2>
          {shown && current ? (
            <CountChip>
              <span aria-live="polite">
                {filtered ? `${shown.length} of ${current.length}` : `${current.length} total`}
              </span>
            </CountChip>
          ) : null}
        </div>

        {error ? (
          <Card className="grid gap-3 p-5">
            <Message tone="error">Couldn’t load your benefits: {error}</Message>
            <div>
              <Button icon={<RefreshCw className="size-4" aria-hidden />} onClick={onRetry}>
                Try again
              </Button>
            </div>
          </Card>
        ) : !shown || !current ? (
          <div aria-busy="true" aria-label="Loading benefits" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-[170px] rounded-[20px]" />
            ))}
          </div>
        ) : current.length === 0 && used.length === 0 ? (
          <Card className="grid justify-items-center gap-2 px-5 py-10 text-center text-ink-muted">
            <Inbox className="size-7" aria-hidden />
            <p className="font-semibold text-ink">Nothing tracked yet</p>
            <p>Add one yourself above, or connect your email or a credit card on the dashboard.</p>
            <Link href="/" className="mt-1 font-semibold text-primary-text underline-offset-4 hover:underline">
              Go to the dashboard
            </Link>
          </Card>
        ) : current.length === 0 ? (
          <Card className="grid justify-items-center gap-2 px-5 py-10 text-center text-ink-muted">
            <CircleCheck className="size-7 text-ok" aria-hidden />
            <p className="font-semibold text-ink">All used</p>
            <p>Everything you tracked is in the Used list below.</p>
          </Card>
        ) : shown.length === 0 ? (
          <Card className="grid justify-items-center gap-3 px-5 py-10 text-center text-ink-muted">
            <Search className="size-7" aria-hidden />
            <p className="font-semibold text-ink">No benefits match these filters</p>
            <Button onClick={() => setFilters((f) => ({ ...NO_FILTERS, sort: f.sort }))}>Clear filters</Button>
          </Card>
        ) : (
          <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_400px]">
            <div className="grid grid-cols-[repeat(auto-fill,minmax(240px,1fr))] gap-4">
              {shown.map((b, i) => (
                <Fragment key={b.id}>
                  <TicketStub
                    benefit={b}
                    index={i}
                    selected={selected?.id === b.id}
                    // Phones: tapping the open ticket closes it.
                    onSelect={() => setSelectedId(!wide && selected?.id === b.id ? null : b.id)}
                  />
                  {!wide && selected?.id === b.id ? detail(b, 'col-span-full') : null}
                </Fragment>
              ))}
            </div>
            {/* Stays in view while the list scrolls; a long ticket scrolls inside it, so its buttons stay reachable.
                The padding keeps the ticket's shadow from being cut off at the scroll edges. */}
            {wide && selected ? (
              <div className="sticky top-24 -m-3 max-h-[calc(100dvh-7.5rem)] overflow-y-auto overscroll-contain p-3 [scrollbar-width:thin]">
                {detail(selected)}
              </div>
            ) : null}
          </div>
        )}
      </section>

      {usedShown.length > 0 ? (
        <Card as="section" aria-label="Used">
          <h3>
            <button
              type="button"
              aria-expanded={usedOpen}
              aria-controls="used-list"
              onClick={() => setUsedOpen((o) => !o)}
              className="flex min-h-11 w-full cursor-pointer items-center gap-2.5 rounded-[20px] px-5 py-3 text-left font-semibold transition-colors duration-150 hover:bg-surface-2/60"
            >
              <ChevronDown
                className={cn('size-4 text-ink-muted transition-transform duration-200', !usedOpen && '-rotate-90')}
                aria-hidden
              />
              Used
              <CountChip>{usedShown.length}</CountChip>
            </button>
          </h3>
          <ul id="used-list" hidden={!usedOpen} className="divide-y divide-line border-t border-line">
            {usedShown.map((b) => (
              <li key={b.id} className="flex items-center gap-3 px-5 py-3 text-ink-muted">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-ink line-through decoration-ink-muted/50">{b.benefit_name}</p>
                  <p className="text-sm">
                    {b.provider ? `${b.provider} · ` : ''}Used {b.used_on ? formatDate(b.used_on) : ''}
                  </p>
                </div>
                <Button icon={<RotateCcw className="size-4" aria-hidden />} onClick={() => restore(b)}>
                  Restore<span className="sr-only"> {b.benefit_name}</span>
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <RecentlyRemoved activeCount={benefits?.length} onRestored={onUpdated} />
    </div>
  )
}
