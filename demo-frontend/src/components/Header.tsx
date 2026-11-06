import {
  ChevronDown,
  CircleUser,
  House,
  ListChecks,
  LogOut,
  MailPlus,
  MessageCircle,
  Moon,
  RotateCcw,
  Sun,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { useArmedAction } from '../hooks/useArmedAction'
import type { User } from '../lib/api'
import { cn } from '../lib/cn'
import { PAGES } from '../lib/router'
import { setTheme, useTheme } from '../lib/theme'
import { Link } from './Link'

const PAGE_ICONS: Record<string, LucideIcon> = {
  '/': House,
  '/benefits': ListChecks,
  '/assistant': MessageCircle,
  '/add': MailPlus,
}

function ThemeToggle() {
  const theme = useTheme()
  const next = theme === 'dark' ? 'light' : 'dark'
  const label = `Switch to ${next} mode`
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={() => setTheme(next)}
      // Phones: borderless, like the account button beside it.
      className="grid size-11 shrink-0 cursor-pointer place-items-center rounded-xl text-ink-muted transition-colors duration-150 hover:bg-surface-2 hover:text-ink sm:border sm:border-line sm:bg-surface sm:text-ink"
    >
      {theme === 'dark' ? <Sun className="size-4" aria-hidden /> : <Moon className="size-4" aria-hidden />}
    </button>
  )
}

interface AccountMenuProps {
  user: User
  /** Leaves the demo for the intro page (the benefit list stays in this browser). */
  onSignOut: () => Promise<void>
  /** Puts the demo back to its sample data. */
  onReset: () => Promise<void>
}

/** AI Lodge demo: no accounts, just the demo profile with "Reset demo data" and "Exit demo". */
function AccountMenu({ user, onSignOut, onReset }: AccountMenuProps) {
  const name = user.name || 'Demo profile'
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [armed, armOrConfirm, disarm] = useArmedAction()
  const panelId = useId()
  const wrapperRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)

  // Close on a click outside, or Escape (focus goes back to the menu button).
  useEffect(() => {
    if (!open) return
    function onPointerDown(e: PointerEvent) {
      if (!wrapperRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== 'Escape') return
      setOpen(false)
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  async function run(action: () => Promise<void>) {
    if (busy) return
    setBusy(true)
    try {
      await action()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      ref={wrapperRef}
      className="relative"
      // Tabbing out of the panel closes it.
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
          setOpen(false)
          disarm()
        }
      }}
    >
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`Demo: ${name}`}
        title={name}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex min-h-11 min-w-11 cursor-pointer items-center justify-center gap-1.5 rounded-xl px-2 text-sm font-medium text-ink-muted transition-colors duration-150 hover:bg-surface-2 hover:text-ink sm:px-3',
          open && 'bg-surface-2 text-ink',
        )}
      >
        <CircleUser className="size-5 shrink-0" aria-hidden />
        <span className="hidden max-w-48 truncate lg:inline">{name}</span>
        <ChevronDown
          className={cn('hidden size-4 shrink-0 transition-transform duration-150 sm:block', open && 'rotate-180')}
          aria-hidden
        />
      </button>

      {open ? (
        <div
          id={panelId}
          className="absolute top-full right-0 z-30 mt-2 grid w-64 max-w-[calc(100vw-2rem)] animate-rise gap-1 rounded-xl glass-float p-1.5"
        >
          <div className="px-2.5 py-2">
            <p className="text-xs text-ink-muted">Demo profile</p>
            <p className="truncate text-sm font-semibold" title={name}>
              {name}
            </p>
            <p className="mt-1 text-xs text-ink-muted">No account: your benefits are kept in this browser only.</p>
          </div>
          <div className="h-px bg-line" aria-hidden />
          <button
            type="button"
            aria-disabled={busy || undefined}
            onClick={() => {
              if (armOrConfirm()) void run(onReset)
            }}
            className={cn(
              'flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 text-sm font-medium text-ink-muted transition-colors duration-150 hover:bg-danger-soft hover:text-danger',
              armed && 'bg-danger-soft text-danger',
            )}
          >
            <RotateCcw className="size-4" aria-hidden />
            {armed ? 'Click again to reset' : 'Reset demo data'}
          </button>
          <button
            type="button"
            aria-disabled={busy || undefined}
            onClick={() => void run(onSignOut)}
            className="flex min-h-11 w-full cursor-pointer items-center gap-2 rounded-lg px-2.5 text-sm font-semibold text-ink transition-colors duration-150 hover:bg-surface-2"
          >
            <LogOut className="size-4" aria-hidden />
            Exit demo
          </button>
        </div>
      ) : null}
    </div>
  )
}

/** The highlight behind the current page's link; it slides when the page changes. */
function useNavPill(path: string) {
  const listRef = useRef<HTMLUListElement>(null)
  const [pill, setPill] = useState<{ left: number; width: number; animate: boolean } | null>(null)
  useLayoutEffect(() => {
    const list = listRef.current
    if (!list) return
    const place = (animate: boolean) => {
      const link = list.querySelector<HTMLElement>('[aria-current="page"]')
      setPill(link ? { left: link.offsetLeft, width: link.offsetWidth, animate } : null)
    }
    place(true)
    // Link widths change between phone and desktop layouts; follow without sliding.
    // (The observer also fires once on start, which would cut the slide short.)
    let first = true
    const ro = new ResizeObserver(() => {
      if (first) first = false
      else place(false)
    })
    ro.observe(list)
    return () => ro.disconnect()
  }, [path])
  return { listRef, pill }
}

interface HeaderProps {
  path: string
  user: User
  onSignOut: () => Promise<void>
  onReset: () => Promise<void>
}

export function Header({ path, user, onSignOut, onReset }: HeaderProps) {
  const { listRef, pill } = useNavPill(path)
  return (
    <header className="sticky top-0 z-20 border-b border-line bg-header backdrop-blur-2xl backdrop-saturate-150">
      <div className="mx-auto flex max-w-6xl items-center gap-1 px-3 py-2.5 min-[360px]:gap-2 min-[360px]:px-4 sm:gap-6 sm:px-6 lg:px-8">
        {/* Left out on the narrowest phones to fit the nav; Home is in it. */}
        <Link
          href="/"
          className="-mx-1 hidden min-h-11 min-w-11 shrink-0 items-center min-[400px]:flex justify-center gap-2.5 rounded-lg px-1 font-bold tracking-tight"
          aria-label="Squirrel, go to the dashboard"
        >
          <img
            src="/icon-192.png"
            alt=""
            width={36}
            height={36}
            className="size-9 rounded-[10px] shadow-[0_6px_18px_-6px_rgb(96_165_250/0.7)]"
          />
          <span className="hidden sm:inline">Squirrel</span>
        </Link>

        <nav aria-label="Pages" className="min-w-0 flex-1">
          <ul ref={listRef} className="relative flex gap-0.5 overflow-x-auto min-[360px]:gap-1 [scrollbar-width:none]">
            {pill ? (
              <li
                role="presentation"
                aria-hidden
                className={cn(
                  'pointer-events-none absolute inset-y-0 rounded-lg bg-primary-soft',
                  pill.animate && 'transition-[left,width] duration-250 ease-[cubic-bezier(.2,.8,.2,1)]',
                )}
                style={{ left: pill.left, width: pill.width }}
              />
            ) : null}
            {PAGES.map((p) => {
              const PageIcon = PAGE_ICONS[p.path]
              return (
                <li key={p.path}>
                  <Link
                    href={p.path}
                    data-nav={p.path}
                    aria-current={path === p.path ? 'page' : undefined}
                    aria-label={p.label}
                    title={p.label}
                    className={cn(
                      'relative flex min-h-11 min-w-11 items-center justify-center gap-1.5 whitespace-nowrap rounded-lg px-2 text-sm font-medium transition-colors duration-150 sm:px-3',
                      path === p.path ? 'text-primary-text' : 'text-ink-muted hover:bg-surface-2 hover:text-ink',
                    )}
                  >
                    {/* Phones: icons, with the current page's name when there's room. */}
                    <PageIcon className="size-5 sm:hidden" aria-hidden />
                    {path === p.path ? <span className="hidden min-[460px]:inline sm:hidden">{p.short}</span> : null}
                    <span className="hidden sm:inline">{p.label}</span>
                  </Link>
                </li>
              )
            })}
          </ul>
        </nav>

        <div className="flex shrink-0 items-center gap-1 sm:gap-2">
          <ThemeToggle />
          <AccountMenu user={user} onSignOut={onSignOut} onReset={onReset} />
        </div>
      </div>
    </header>
  )
}
