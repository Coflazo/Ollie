import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { api, type Candidate, type Question, type Read } from '../api'
import { Button, Chip, Panel, Waiting, riseIn } from '../ui'

type Done = { read: Read; candidates: Candidate[]; matching: Matching }
export type Matching = {
  user_type: string
  user_type_source: 'entered' | 'inferred'
  user_type_description: string
  axis_confidence: Record<string, number>
  ranked: { type: string; score: number; reason: string; description: string }[]
  basis: string
}

const TYPES = [
  'ISTJ', 'ISFJ', 'INFJ', 'INTJ', 'ISTP', 'ISFP', 'INFP', 'INTP',
  'ESTP', 'ESFP', 'ENFP', 'ENTP', 'ESTJ', 'ESFJ', 'ENFJ', 'ENTJ',
]

export function Onboarding({ onDone }: { onDone: (d: Done) => void }) {
  const [phase, setPhase] = useState<'form' | 'interview'>('form')
  const [questions, setQuestions] = useState<Question[]>([])
  const [answers, setAnswers] = useState<Record<string, number>>({})
  const [name, setName] = useState('')
  const [knownType, setKnownType] = useState('')
  const [mature, setMature] = useState(false)
  const [adult, setAdult] = useState(false)

  const [turn, setTurn] = useState({ n: 1, total: 5 })
  const [thread, setThread] = useState<{ role: 'ollie' | 'you'; text: string }[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    api.questions().then((q) => setQuestions(q.items))
  }, [])
  useEffect(() => {
    if (phase === 'interview' && !busy) inputRef.current?.focus()
  }, [phase, busy, thread.length])

  const complete = questions.length > 0 && Object.keys(answers).length === questions.length

  async function startInterview() {
    setBusy(true)
    try {
      const res = await api.submitQuestionnaire(
        answers,
        { content_mode: mature ? 'mature' : 'general', adult_confirmed: adult },
        name,
        knownType,
      )
      setThread([{ role: 'ollie', text: res.question }])
      setTurn({ n: res.turn, total: res.total })
      setPhase('interview')
    } finally {
      setBusy(false)
    }
  }

  async function answer() {
    const text = draft.trim()
    if (!text || busy) return
    setThread((t) => [...t, { role: 'you', text }])
    setDraft('')
    setBusy(true)
    try {
      const res = await api.answerInterview(text)
      if (res.done) {
        onDone(res as unknown as Done)
      } else {
        setThread((t) => [...t, { role: 'ollie', text: res.question }])
        setTurn({ n: res.turn, total: res.total })
      }
    } finally {
      setBusy(false)
    }
  }

  if (phase === 'form') {
    return (
      <div className="mx-auto max-w-2xl px-6 py-14">
        <motion.div {...riseIn}>
          <h2 className="text-2xl font-medium tracking-tight">First, roughly who you are</h2>
          <p className="mt-2 text-[15px] text-[var(--color-muted)]">
            Ten statements. Answer how you actually are, not how you&rsquo;d like to be — the
            interview afterwards will catch the difference anyway.
          </p>
        </motion.div>

        <div className="mt-8 space-y-1">
          {questions.map((q, i) => (
            <motion.div
              key={q.id}
              {...riseIn}
              transition={{ ...riseIn.transition, delay: Math.min(i * 0.03, 0.3) }}
              className="flex items-center justify-between gap-6 rounded-lg px-3 py-2.5
                         hover:bg-[var(--color-surface)]"
            >
              <span className="text-[14px] leading-snug">{q.text}</span>
              <div className="flex shrink-0 gap-1">
                {[1, 2, 3, 4, 5].map((v) => (
                  <button
                    key={v}
                    onClick={() => setAnswers((a) => ({ ...a, [q.id]: v }))}
                    aria-label={`${q.text}: ${v} of 5`}
                    className={`size-7 rounded-md border text-[12px] transition-colors ${
                      answers[q.id] === v
                        ? 'border-[var(--color-warm)] bg-[var(--color-warm)] text-[var(--color-ink)]'
                        : 'border-[var(--color-line)] text-[var(--color-faint)] hover:border-[var(--color-faint)]'
                    }`}
                  >
                    {v}
                  </button>
                ))}
              </div>
            </motion.div>
          ))}
        </div>

        <div className="mt-8 grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5">
            <span className="text-[12px] text-[var(--color-faint)]">what should they call you</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-[var(--color-line)] bg-[var(--color-surface)]
                         px-3 py-2 text-sm outline-none focus:border-[var(--color-faint)]"
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-[12px] text-[var(--color-faint)]">
              already know your type? (optional)
            </span>
            <select
              value={knownType}
              onChange={(e) => setKnownType(e.target.value)}
              className="w-full rounded-lg border border-[var(--color-line)] bg-[var(--color-surface)]
                         px-3 py-2 text-sm outline-none focus:border-[var(--color-faint)]"
            >
              <option value="">work it out from the interview</option>
              {TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </label>
        </div>

        <Panel className="mt-6">
          <label className="flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              checked={mature}
              onChange={(e) => {
                setMature(e.target.checked)
                if (!e.target.checked) setAdult(false)
              }}
              className="mt-0.5 accent-[var(--color-warm)]"
            />
            <span className="text-[13px] leading-relaxed">
              <span className="text-[var(--color-text)]">Mature mode</span>
              <span className="text-[var(--color-muted)]">
                {' '}
                — explicit content is available. Off by default. You can switch it back at any
                point, and nothing sexual is exported anywhere.
              </span>
            </span>
          </label>
          <AnimatePresence>
            {mature && (
              <motion.label
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="mt-3 flex cursor-pointer items-center gap-3 overflow-hidden border-t
                           border-[var(--color-line)] pt-3"
              >
                <input
                  type="checkbox"
                  checked={adult}
                  onChange={(e) => setAdult(e.target.checked)}
                  className="accent-[var(--color-warm)]"
                />
                <span className="text-[13px] text-[var(--color-muted)]">
                  I confirm I am 18 or over.
                </span>
              </motion.label>
            )}
          </AnimatePresence>
        </Panel>

        <div className="mt-6 flex items-center gap-4">
          <Button onClick={startInterview} disabled={!complete || busy || (mature && !adult)}>
            {busy ? 'thinking…' : 'next'}
          </Button>
          <span className="text-[12px] text-[var(--color-faint)]">
            {Object.keys(answers).length} of {questions.length}
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col px-6 py-14">
      <motion.div {...riseIn}>
        <h2 className="text-2xl font-medium tracking-tight">Now the actual questions</h2>
        <p className="mt-2 text-[15px] text-[var(--color-muted)]">
          Ollie is reading how you answer, not just what you answer. Question {turn.n} of{' '}
          {turn.total}.
        </p>
      </motion.div>

      <div className="mt-8 flex-1 space-y-5">
        <AnimatePresence initial={false}>
          {thread.map((m, i) => (
            <motion.div key={i} {...riseIn} layout>
              {m.role === 'ollie' ? (
                <p className="text-[17px] leading-relaxed">{m.text}</p>
              ) : (
                <p className="border-l-2 border-[var(--color-line)] pl-4 text-[14px] leading-relaxed
                              text-[var(--color-muted)]">
                  {m.text}
                </p>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
        {/* The last answer is not like the other four. It also extracts your traits and
            writes three people, which measured at 78s against 1.4-1.9s for the turns
            before it. Identical feedback for both is what made this look frozen. */}
        {busy &&
          (turn.n >= turn.total ? (
            <Waiting
              label="reading everything you said"
              hint="working out your type, ranking all sixteen, and writing three people to
                    match. this is the long one — a minute or so."
            />
          ) : (
            <Waiting label="thinking about that" />
          ))}
      </div>

      <div className="mt-6">
        <textarea
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void answer()
            }
          }}
          rows={3}
          placeholder="be honest, it works better"
          className="w-full resize-none rounded-lg border border-[var(--color-line)]
                     bg-[var(--color-surface)] px-4 py-3 text-[15px] leading-relaxed outline-none
                     placeholder:text-[var(--color-faint)] focus:border-[var(--color-faint)]"
        />
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={answer} disabled={!draft.trim() || busy}>
            send
          </Button>
          <Chip tone="quiet">enter to send</Chip>
        </div>
      </div>
    </div>
  )
}
