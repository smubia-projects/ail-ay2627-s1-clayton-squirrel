import { FileUp, Inbox, MailPlus, Sparkles } from 'lucide-react'
import { useMemo, useRef, useState, type ChangeEvent, type FormEvent } from 'react'
import { sampleInbox, sampleText, type SampleEmail } from '../demo/sampleInbox'
import { isQuotaError } from '../lib/aiApi'
import { api, errorMessage, type Benefit, type EmailInput } from '../lib/api'
import { cn } from '../lib/cn'
import { formatDate } from '../lib/format'
import { fieldClass } from '../lib/styles'
import { navigate } from '../lib/router'
import { useToast } from '../lib/toast'
import { Button } from './ui/Button'
import { Card, CardHeader } from './ui/Card'
import { Message } from './ui/Message'

const MAX_EML_BYTES = 2_000_000

type Outcome =
  | { kind: 'added'; benefit: Benefit; from: string }
  | { kind: 'skipped'; from: string }
  | { kind: 'error'; message: string }

interface EmailImportPanelProps {
  /** A benefit the AI found, already saved in the list. */
  onAdded: (benefit: Benefit) => void
}

/**
 * AI Lodge demo: instead of connecting an inbox, the visitor hands Squirrel one
 * email at a time (pasted, an uploaded .eml file, or one from the sample inbox).
 * Each is read by the real AI extractor (POST /api/extract on the backend).
 */
export function EmailImportPanel({ onAdded }: EmailImportPanelProps) {
  const toast = useToast()
  const samples = useMemo(() => sampleInbox(), [])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  async function read(key: string, email: EmailInput, from: string) {
    if (busy) return
    setBusy(key)
    setOutcome(null)
    try {
      const { benefit } = await api.extract(email)
      if (benefit) {
        onAdded(benefit)
        setOutcome({ kind: 'added', benefit, from })
        toast('success', benefit.needs_review ? 'Found a benefit to review.' : `Added ${benefit.benefit_name}.`, {
          label: benefit.needs_review ? 'Review' : 'See it',
          onClick: () => navigate(benefit.needs_review ? '/#review' : `/benefits#benefit-${benefit.id}`),
        })
      } else {
        setOutcome({ kind: 'skipped', from })
      }
      return true
    } catch (e) {
      // The rate-limit CTA / paused notice is shown as a modal instead.
      if (!isQuotaError(e)) setOutcome({ kind: 'error', message: errorMessage(e) })
      return false
    } finally {
      setBusy(null)
    }
  }

  async function submitText(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (text.trim().length < 20) {
      setOutcome({ kind: 'error', message: 'Paste a whole email first (at least a sentence or two).' })
      return
    }
    if (await read('paste', { text, label: 'Pasted email' }, 'the pasted email')) setText('')
  }

  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // so picking the same file again still fires
    if (!file) return
    if (file.size > MAX_EML_BYTES) {
      setOutcome({ kind: 'error', message: 'That file is over 2 MB. Save the email without attachments and try again.' })
      return
    }
    const raw = await file.text()
    await read('file', { eml: raw, label: file.name }, file.name)
  }

  const readSample = (s: SampleEmail) =>
    read(`sample:${s.id}`, { text: sampleText(s), received_date: s.received, label: s.subject }, `“${s.subject}”`)

  return (
    <Card as="section" aria-labelledby="import-title" className="grid content-start">
      <CardHeader icon={MailPlus} title="Find benefits in an email" titleId="import-title" />
      <div className="grid gap-5 p-5">
        <p className="text-ink-muted">
          Squirrel’s AI reads one email and pulls out the benefit, its value, code and expiry date. Plain code then
          checks the result: dates it isn’t sure of go to your review queue.
        </p>

        <form className="grid gap-2" onSubmit={submitText} noValidate>
          <label htmlFor="email-text" className="text-sm font-semibold">
            Paste an email
          </label>
          <textarea
            id="email-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            maxLength={50_000}
            placeholder="Subject: Your birthday treat is here…"
            className={cn(fieldClass, 'min-h-32 resize-y border-line font-[inherit]')}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              variant="primary"
              icon={<Sparkles className="size-4" aria-hidden />}
              loading={busy === 'paste'}
              loadingLabel="Reading…"
              aria-disabled={(busy !== null && busy !== 'paste') || undefined}
            >
              Find the benefit
            </Button>
            <Button
              icon={<FileUp className="size-4" aria-hidden />}
              loading={busy === 'file'}
              loadingLabel="Reading…"
              onClick={() => !busy && fileRef.current?.click()}
            >
              Upload an .eml file
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept=".eml,message/rfc822"
              className="sr-only"
              tabIndex={-1}
              aria-hidden
              onChange={upload}
            />
          </div>
          <p className="text-xs text-ink-muted">
            Most mail apps can save an email as .eml (Gmail: ⋮ → Download message). The email is sent to an AI model
            through OpenRouter and isn’t stored.
          </p>
        </form>

        <div aria-live="polite" className="grid gap-2 empty:hidden">
          {outcome?.kind === 'added' ? (
            <Message tone={outcome.benefit.needs_review ? 'warn' : 'success'}>
              <strong>{outcome.benefit.benefit_name}</strong>
              {outcome.benefit.provider ? ` (${outcome.benefit.provider})` : ''} found in {outcome.from}.{' '}
              {outcome.benefit.needs_review
                ? `It’s in your review queue: ${outcome.benefit.review_reason ?? 'the date needs checking'}.`
                : outcome.benefit.expiry_date
                  ? `Expires ${formatDate(outcome.benefit.expiry_date)}.`
                  : 'No expiry date.'}
            </Message>
          ) : outcome?.kind === 'skipped' ? (
            <Message tone="info">No benefit in {outcome.from}: it looks like marketing or an unrelated email, so nothing was added.</Message>
          ) : outcome?.kind === 'error' ? (
            <Message tone="error">{outcome.message}</Message>
          ) : null}
        </div>

        <div className="grid gap-2">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Inbox className="size-4 text-ink-muted" aria-hidden />
            Or try the sample inbox
          </h3>
          <ul className="grid gap-2">
            {samples.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-3 rounded-xl bg-surface-2 px-3.5 py-2.5">
                <span className="grid min-w-0 flex-1">
                  <span className="truncate font-semibold">{s.subject}</span>
                  <span className="truncate text-xs text-ink-muted">
                    {s.from.replace(/\s*<.*>$/, '')} · {s.note}
                  </span>
                </span>
                <Button
                  className="min-h-10"
                  loading={busy === `sample:${s.id}`}
                  loadingLabel="Reading…"
                  aria-disabled={(busy !== null && busy !== `sample:${s.id}`) || undefined}
                  onClick={() => void readSample(s)}
                >
                  Read it
                </Button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </Card>
  )
}
