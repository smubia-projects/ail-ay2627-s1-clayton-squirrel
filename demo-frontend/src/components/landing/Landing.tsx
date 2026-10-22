import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { LandingArt } from './LandingArt'
import { Snowball } from './Snowball'
import { useLandingMotion } from './useLandingMotion'

// The intro page, from the Claude Design file "Squirrel Login": a scrolling
// introduction (big "Squirrel", how it works, the kinds of benefit it tracks).
// AI Lodge demo: there are no accounts, so every call to action opens the demo.
// Colours are the --land-* tokens in index.css.

interface LandingProps {
  /** Opens the demo (with the sample benefits on first visit). */
  onStart: () => Promise<void>
}

const delay = (ms: number) => ({ '--d': `${ms}ms` }) as CSSProperties

const HERO_WORDS = 'Never let a voucher expire unnoticed.'.split(' ')

const LEAVES = [
  { left: '58%', top: '16%', size: 22, color: '#D9481F', rot: 20, speed: 0.12 },
  {
    left: '70%',
    top: '50%',
    size: 16,
    color: '#E9B44C',
    rot: -30,
    speed: -0.4,
  },
  { left: '82%', top: '30%', size: 28, color: '#E9B44C', rot: 60, speed: 0.2 },
  {
    left: '46%',
    top: '64%',
    size: 14,
    color: '#D9481F',
    rot: -10,
    speed: -0.25,
  },
  { left: '90%', top: '58%', size: 18, color: '#C2410C', rot: 40, speed: 0.08 },
  { left: '64%', top: '34%', size: 12, color: '#C2410C', rot: 75, speed: -0.5 },
  { left: '76%', top: '12%', size: 15, color: '#D9481F', rot: -55, speed: 0.3 },
]

const STEPS = [
  {
    n: '01',
    title: 'Paste an email, add your cards',
    body: 'Paste a benefit email, upload an .eml file or try the sample inbox, and pick your credit cards from a list.',
  },
  {
    n: '02',
    title: 'Squirrel finds what you’re owed',
    body: 'Vouchers, memberships, card credits and loyalty rewards land in one list, each with its expiry date.',
  },
  {
    n: '03',
    title: 'Use it before it’s gone',
    body: 'See what expires soonest, get an AI digest of what needs attention, and ask questions about what you hold.',
  },
]

// Examples for the sideways cards, each tinted by hue.
const TILES = [
  {
    kind: 'Voucher',
    value: '£5',
    title: 'Coffee shop reward',
    icon: 'coffee',
    expiry: '3 days',
    hue: 55,
  },
  {
    kind: 'Card credit',
    value: '$15',
    title: 'Monthly dining credit',
    icon: 'pizza',
    expiry: '9 days',
    hue: 145,
  },
  {
    kind: 'Membership',
    value: '2×',
    title: 'Airport lounge passes',
    icon: 'lounge',
    expiry: '6 weeks',
    hue: 255,
  },
  {
    kind: 'Gift card',
    value: '£25',
    title: 'Birthday gift card',
    icon: 'cake',
    expiry: '2 months',
    hue: 330,
  },
  {
    kind: 'Streaming',
    value: '1 mo',
    title: 'Free trial ends',
    icon: 'tv',
    expiry: '5 days',
    hue: 20,
  },
  {
    kind: 'Loyalty',
    value: '4,200',
    title: 'Airline points',
    icon: 'plane',
    expiry: '4 months',
    hue: 200,
  },
]
const tileBg = (h: number) => `oklch(var(--land-tile-l) var(--land-tile-c) ${h})`
const tileInk = (h: number) => `oklch(var(--land-tile-ink-l) 0.13 ${h})`

// Plain answers about how the demo handles email.
const DATA_FACTS = [
  {
    title: 'No inbox access',
    body: 'This demo never connects to your email account. It reads only the emails you paste or upload, one at a time.',
  },
  {
    title: 'Processed by AI, not kept',
    body: 'Each email is sent through OpenRouter to an AI model to pull out the benefit and its date. The server stores nothing.',
  },
  {
    title: 'Stays in your browser',
    body: 'Your benefit list lives in this browser only. Reset the demo from the account menu to clear it.',
  },
  {
    title: 'Checked by plain code',
    body: 'Dates the AI isn’t sure of go to a review queue, and a voucher code is kept only if it appears word for word in the email.',
  },
]

const PROMISE =
  'Squirrel never asks for card numbers, bank logins or email passwords. It reads only the emails you give it.'

/** A hill along the bottom of the hero, stretched to fill its box. */
function Hill({ d, fill }: { d: string; fill: string }) {
  return (
    <svg viewBox="0 0 1440 400" preserveAspectRatio="none" className="block size-full" aria-hidden>
      <path d={d} fill={fill} />
    </svg>
  )
}

export function Landing({ onStart }: LandingProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  useLandingMotion(rootRef, 'landing')
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    document.title = 'Squirrel'
  }, [])

  async function start() {
    if (starting) return
    setStarting(true)
    try {
      await onStart()
    } finally {
      setStarting(false)
    }
  }

  return (
    <div ref={rootRef} className="relative isolate min-h-dvh overflow-x-clip bg-(--land-bg) text-ink">
      <LandingArt />
      {/* Soft colour patches behind everything, drifting at different speeds. */}
      <div aria-hidden className="pointer-events-none fixed inset-0 -z-1">
        {[
          'left-[-180px] top-[-120px] size-[640px] [--blob:var(--land-blob-1)]',
          'right-[-200px] top-10 size-[720px] [--blob:var(--land-blob-2)]',
          'left-[10%] top-[70vh] size-[620px] [--blob:var(--land-blob-3)]',
        ].map((c, i) => (
          <div
            key={c}
            data-parallax={[0.12, -0.08, 0.2][i]}
            className={`absolute rounded-full bg-[radial-gradient(closest-side,var(--blob),transparent)] ${c}`}
          />
        ))}
      </div>

      <header
        data-header
        className="group fixed inset-x-0 top-0 z-50 py-[22px] transition-[background-color,padding,box-shadow] duration-300 data-scrolled:bg-(--land-header) data-scrolled:py-2.5 data-scrolled:shadow-[0_1px_0_var(--color-line)] data-scrolled:backdrop-blur-md"
      >
        <div className="mx-auto flex max-w-[1200px] items-center justify-between gap-4 px-4 sm:px-8">
          <button
            type="button"
            onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
            className="flex min-h-11 cursor-pointer items-center gap-2.5 rounded-lg"
            aria-label="Squirrel, back to the top"
          >
            <img
              src="/icon-192.png"
              alt=""
              width={36}
              height={36}
              className="size-9 rounded-[10px] transition-[width,height] duration-300 group-data-scrolled:size-[30px]"
            />
            <span className="text-lg font-bold tracking-tight">Squirrel</span>
          </button>
          <button
            type="button"
            aria-disabled={starting || undefined}
            onClick={start}
            className="min-h-11 cursor-pointer rounded-full border border-line bg-surface px-4 text-sm font-semibold transition-colors hover:border-ink"
          >
            Try the demo
          </button>
        </div>
        <div aria-hidden className="absolute inset-x-0 bottom-0 h-0.5">
          <div data-progress className="h-full w-0 bg-cta" />
        </div>
      </header>

      {
        <main>
          <Hero />
          <div className="mx-auto max-w-[1200px] px-4 sm:px-8">
            <div className="mx-auto max-w-[760px]">
              <Steps />
              <Tiles />
              <section data-fillsec className="pt-20 pb-40">
                <p className="m-0 flex flex-wrap gap-x-[.26em] text-[clamp(30px,3.8vw,46px)] leading-[1.2] font-bold tracking-[-0.025em]">
                  {PROMISE.split(' ').map((w, i) => (
                    <span key={i} data-fill className="opacity-[.18]">
                      {w}
                    </span>
                  ))}
                </p>
              </section>
              <section aria-labelledby="data-title" className="grid gap-6 pb-24">
                <h2
                  id="data-title"
                  data-reveal="up"
                  className="m-0 text-[clamp(28px,3.4vw,40px)] leading-[1.1] font-extrabold tracking-[-0.03em]"
                >
                  How Squirrel uses your email
                </h2>
                <dl className="m-0 grid gap-x-8 gap-y-5 sm:grid-cols-2">
                  {DATA_FACTS.map((f, i) => (
                    <div key={f.title} data-reveal="up" style={delay(i * 80)} className="grid gap-1">
                      <dt className="text-lg font-bold">{f.title}</dt>
                      <dd className="m-0 text-ink-muted">{f.body}</dd>
                    </div>
                  ))}
                </dl>
              </section>
              <section className="flex flex-col-reverse gap-8 pt-10 pb-36 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-col items-start gap-6">
                  <h2
                    data-reveal="up"
                    className="m-0 text-[clamp(36px,4.6vw,56px)] leading-[1.05] font-extrabold tracking-[-0.035em] text-balance sm:whitespace-nowrap"
                  >
                    Ready when you are.
                  </h2>
                  <button
                    type="button"
                    data-reveal="up"
                    style={delay(120)}
                    aria-disabled={starting || undefined}
                    onClick={start}
                    className="min-h-11 cursor-pointer rounded-full bg-ink px-6.5 py-3.5 text-base font-semibold text-(--land-bg) transition-colors hover:bg-cta hover:text-white"
                  >
                    Try the demo
                  </button>
                </div>
                <div data-reveal="up" style={delay(240)} className="w-[200px] shrink-0">
                  <Snowball className="block h-auto w-full" />
                </div>
              </section>
            </div>
          </div>
          <footer className="border-t border-line">
            <div className="mx-auto flex max-w-[1200px] flex-wrap items-center gap-x-6 gap-y-1 px-4 py-6 text-sm text-ink-muted sm:px-8">
              <span>© 2026 Squirrel</span>
              <a
                href="https://www.smubia.com/ailodge"
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-11 items-center underline-offset-4 hover:text-ink hover:underline"
              >
                An SMU BIA AI Lodge project
              </a>
              <a
                href="mailto:squirrelappsg@gmail.com"
                className="inline-flex min-h-11 items-center underline-offset-4 hover:text-ink hover:underline"
              >
                squirrelappsg@gmail.com
              </a>
            </div>
          </footer>
        </main>
      }
    </div>
  )
}

function Hero() {
  return (
    <section className="relative flex min-h-dvh items-center overflow-hidden">
      <div data-parallax="-0.06" className="absolute inset-x-0 bottom-0 h-[60%]">
        <Hill
          d="M0 180 C240 80 420 120 640 170 C860 220 1080 90 1440 150 L1440 400 L0 400Z"
          fill="var(--land-hill-far)"
        />
      </div>
      <div data-parallax="-0.16" className="absolute inset-x-0 bottom-0 h-[46%]">
        <Hill
          d="M0 200 C200 120 480 230 720 170 C980 110 1200 200 1440 140 L1440 400 L0 400Z"
          fill="var(--land-hill-near)"
        />
      </div>
      <div className="absolute inset-x-0 -bottom-px h-[30%]">
        <Hill d="M0 150 C260 70 520 200 800 140 C1060 90 1260 170 1440 110 L1440 400 L0 400Z" fill="var(--land-bg)" />
      </div>

      <div
        data-parallax="-0.32"
        data-rot="14"
        data-spin="0.08"
        aria-hidden
        className="absolute top-[18%] right-[13%] z-4 w-[clamp(72px,10vw,124px)]"
      >
        <div data-reveal="drop" style={delay(900)}>
          <svg viewBox="0 0 40 52" className="block w-full">
            <use href="#land-sq-acorn" />
          </svg>
        </div>
      </div>
      {LEAVES.map((l, i) => (
        <span
          key={i}
          aria-hidden
          data-parallax={l.speed}
          data-rot={l.rot}
          data-sway={i}
          className="absolute z-4"
          style={{ left: l.left, top: l.top, width: l.size, height: l.size }}
        >
          <span
            data-reveal="pop"
            className="block size-full rounded-[0_100%_0_100%]"
            style={{ ...delay(1000 + i * 80), background: l.color }}
          />
        </span>
      ))}

      <div
        data-parallax="-0.35"
        className="relative z-5 mx-auto w-full max-w-[1200px] px-4 pt-[120px] pb-[22vh] sm:px-8"
      >
        <h1
          tabIndex={-1}
          aria-label="Squirrel"
          // The bottom margin grows with the type: the "q" hangs ~.2em below the line box.
          className="m-0 mb-[calc(.22em+20px)] flex text-[clamp(72px,17vw,232px)] leading-[.9] font-extrabold tracking-[-0.055em] outline-none"
        >
          {'Squirrel'.split('').map((ch, i) => (
            <span key={i} aria-hidden data-reveal="letter" className="inline-block" style={delay(100 + i * 70)}>
              {ch}
            </span>
          ))}
        </h1>
        <p className="m-0 flex max-w-[16em] flex-wrap gap-x-[.24em] text-[clamp(26px,3.4vw,42px)] leading-[1.1] font-bold tracking-[-0.03em]">
          {HERO_WORDS.map((w, i) => (
            <span
              key={i}
              data-reveal="word"
              className={i === HERO_WORDS.length - 1 ? 'inline-block text-cta' : 'inline-block'}
              style={delay(700 + i * 70)}
            >
              {w}
            </span>
          ))}
        </p>
        <p
          data-reveal="up"
          style={delay(1100)}
          className="mt-[18px] mb-0 max-w-[30em] text-lg leading-[1.55] text-ink-muted"
        >
          Paste a benefit email or pick your cards, and never let a voucher, membership or card credit expire unnoticed.
        </p>
      </div>
    </section>
  )
}

function Steps() {
  return (
    <section data-pin={STEPS.length} className="relative h-[300vh]" aria-label="How it works">
      <div className="sticky top-0 flex h-dvh items-center gap-6 sm:gap-10">
        <svg width="60" height="400" viewBox="0 0 60 400" className="flex-none overflow-visible" aria-hidden>
          <path
            d="M30 10 C 60 80, 0 130, 30 200 S 60 320, 30 390"
            fill="none"
            stroke="var(--land-line)"
            strokeWidth="2"
          />
          <path
            data-draw
            d="M30 10 C 60 80, 0 130, 30 200 S 60 320, 30 390"
            fill="none"
            stroke="var(--color-cta)"
            strokeWidth="2.5"
            strokeLinecap="round"
          />
          {[10, 200, 390].map((cy, i) => (
            <g
              key={cy}
              data-node={i}
              data-cy={cy}
              transform={`translate(30 ${cy}) scale(.85)`}
              className="transition-opacity duration-400"
            >
              <use href="#land-sq-acorn" x="-14" y="-20" width="28" height="36" />
            </g>
          ))}
        </svg>
        <div className="relative h-[340px] min-w-0 flex-1">
          {STEPS.map((s, i) => (
            <div
              key={s.n}
              data-step={i}
              className="absolute inset-0 flex flex-col justify-center opacity-0 transition-[opacity,transform] duration-500 ease-[cubic-bezier(.2,.7,.2,1)]"
            >
              <span
                aria-hidden
                className="text-[clamp(80px,10vw,120px)] leading-none font-extrabold tracking-[-0.05em] text-transparent [-webkit-text-stroke:1.5px_var(--land-outline)]"
              >
                {s.n}
              </span>
              <h2 className="mt-2 mb-3.5 text-[clamp(30px,3.6vw,44px)] leading-[1.08] font-extrabold tracking-[-0.03em]">
                {s.title}
              </h2>
              <p className="m-0 max-w-[28em] text-lg leading-relaxed text-ink-muted">{s.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function Tiles() {
  return (
    <section data-hscroll className="relative h-[260vh]">
      {/* The cards may slide past the column's edge; the page clips them at the screen edge. */}
      <div className="sticky top-0 flex h-dvh flex-col justify-center gap-8">
        <h2
          data-reveal="up"
          className="m-0 max-w-[14em] text-[clamp(30px,3.6vw,44px)] leading-[1.08] font-extrabold tracking-[-0.03em]"
        >
          Everything Squirrel keeps an eye on
        </h2>
        <ul data-track className="m-0 flex w-max list-none gap-4 p-0 will-change-transform">
          {TILES.map((t) => (
            <li
              key={t.title}
              className="flex h-80 w-[270px] flex-col justify-between rounded-[22px] border border-black/5 p-6"
              style={{ background: tileBg(t.hue) }}
            >
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-bold tracking-[.06em] uppercase" style={{ color: tileInk(t.hue) }}>
                  {t.kind}
                </span>
                <span
                  className="rounded-full bg-white px-2.5 py-1 text-xs font-bold"
                  style={{ color: `oklch(0.45 0.13 ${t.hue})` }}
                >
                  {t.expiry}
                </span>
              </div>
              <svg viewBox="0 0 200 200" className="size-[124px] self-center overflow-visible" aria-hidden>
                <use href={`#land-ic-${t.icon}`} />
              </svg>
              <div>
                <div className="text-[44px] font-extrabold tracking-[-0.03em]" style={{ color: tileInk(t.hue) }}>
                  {t.value}
                </div>
                <div className="mt-1.5 text-[17px] font-semibold">{t.title}</div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
