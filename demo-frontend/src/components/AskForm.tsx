import { ArrowUp, Sparkles } from 'lucide-react'
import { useState, type FormEvent, type Ref } from 'react'
import { isQuotaError } from '../lib/aiApi'
import { api, errorMessage, type AskEntry } from '../lib/api'
import { cn } from '../lib/cn'
import { Kbd } from './ui/Kbd'
import { Card } from './ui/Card'
import { Message } from './ui/Message'

interface AskFormProps {
  inputRef: Ref<HTMLInputElement>
  /** Called with each answered question; the page shows it in the history. */
  onAsked: (entry: AskEntry) => void
}

/** Questions to start from; tapping one asks it straight away. */
const SUGGESTIONS = [
  'What should I use this week?',
  'Which card has a dining credit?',
  'Do I have any travel perks?',
  'How many points do I have?',
]

/** "Squirrel is thinking" with three bouncing dots, while an answer is on its way. */
function TypingIndicator() {
  return (
    <div className="flex items-center gap-3 justify-self-start rounded-xl bg-surface-2 px-4 py-3">
      <span className="text-sm text-ink-muted">Squirrel is thinking</span>
      <span aria-hidden className="flex gap-1">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="size-2 animate-typing rounded-full bg-ink-muted"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>
    </div>
  )
}

export function AskForm({ inputRef, onAsked }: AskFormProps) {
  const [question, setQuestion] = useState('')
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [asked, setAsked] = useState('')

  async function ask(text: string) {
    setFieldError(null)
    setError(null)
    setLoading(true)
    setAsked(text.trim())
    try {
      onAsked(await api.ask(text))
      setQuestion('')
    } catch (err) {
      // The rate-limit CTA / paused notice is shown as a modal instead.
      if (!isQuotaError(err)) setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    if (loading) return
    if (!question.trim()) {
      setFieldError('Type a question first.')
      e.currentTarget.querySelector('input')?.focus()
      return
    }
    await ask(question)
  }

  return (
    <Card as="section" id="ask" aria-labelledby="ask-title" className="grid gap-4 p-5 sm:p-6">
      <div className="flex items-center gap-3">
        <span aria-hidden className="grid size-11 shrink-0 place-items-center rounded-[14px] bg-[#FCD34D] text-[#1C1917]">
          <Sparkles className="size-6" />
        </span>
        <h2 id="ask-title" className="flex-1 text-xl font-extrabold tracking-tight">
          Ask Squirrel
        </h2>
        <Kbd>/</Kbd>
      </div>

      <div aria-live="polite" className="grid gap-2 empty:hidden">
        {loading ? (
          <div className="grid animate-rise gap-2">
            <p className="max-w-[80%] justify-self-end rounded-[20px_20px_4px_20px] bg-ink px-4 py-2.5 font-semibold text-bg">
              {asked}
            </p>
            <TypingIndicator />
          </div>
        ) : error ? (
          <Message tone="error">{error}</Message>
        ) : null}
      </div>

      <div className="grid gap-2">
        <p className="text-sm text-ink-muted">Try asking</p>
        <div className="flex flex-wrap gap-2">
          {SUGGESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              aria-disabled={loading || undefined}
              onClick={() => {
                if (loading) return
                setQuestion(q)
                void ask(q)
              }}
              className="min-h-10 cursor-pointer rounded-full border border-primary/40 bg-primary-soft px-4 text-sm font-medium transition-colors duration-150 hover:bg-primary/25 aria-disabled:cursor-not-allowed aria-disabled:opacity-60"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      <form className="grid gap-1.5" onSubmit={handleSubmit} noValidate>
        <label htmlFor="question" className="sr-only">
          Question
        </label>
        <div
          className={cn(
            'flex min-h-14 items-center gap-2 rounded-[18px] border bg-surface py-1.5 pr-1.5 pl-4 transition-colors duration-150 focus-within:border-primary focus-within:ring-2 focus-within:ring-focus hover:border-ink-muted/50',
            fieldError ? 'border-danger' : 'border-line',
          )}
        >
          <input
            id="question"
            ref={inputRef}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            autoComplete="off"
            enterKeyHint="send"
            aria-invalid={fieldError ? true : undefined}
            aria-describedby={fieldError ? 'question-error' : 'question-hint'}
            placeholder="Ask about your benefits…"
            className="min-w-0 flex-1 bg-transparent outline-none"
          />
          <button
            type="submit"
            aria-label={loading ? 'Thinking…' : 'Ask'}
            aria-disabled={loading || undefined}
            className="grid size-11 shrink-0 cursor-pointer place-items-center rounded-[14px] bg-cta text-white transition-colors duration-150 hover:bg-cta-hover aria-disabled:cursor-not-allowed aria-disabled:opacity-70"
          >
            <ArrowUp className="size-5" strokeWidth={2.4} aria-hidden />
          </button>
        </div>
        {fieldError ? (
          <p id="question-error" role="alert" className="text-sm font-medium text-danger">
            {fieldError}
          </p>
        ) : (
          <p id="question-hint" className="text-xs text-ink-muted">
            Answers use only the benefits you’re tracking, not outside knowledge.
          </p>
        )}
      </form>
    </Card>
  )
}
