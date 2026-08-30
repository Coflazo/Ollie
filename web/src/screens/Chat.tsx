import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import {
  api,
  type Candidate,
  type Capsule,
  type Context,
  type Explanation,
  type MemoryRecord,
} from '../api'
import { Button, Chip, Meter, Panel, ease, riseIn } from '../ui'

type Bubble = {
  role: 'you' | 'them'
  text: string
  explanation?: Explanation
  latency?: number
}

export function Chat({ persona, model }: { persona: Candidate; model: string | null }) {
  const [bubbles, setBubbles] = useState<Bubble[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [ctx, setCtx] = useState<Context | null>(null)
  const [openDrawer, setOpenDrawer] = useState<number | null>(null)
  const [memories, setMemories] = useState<MemoryRecord[]>([])
  const [capsule, setCapsule] = useState<{ id: string; data: Capsule } | null>(null)
  const [episode, setEpisode] = useState(1)

  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [bubbles.length, busy])

  useEffect(() => {
    if (!busy) inputRef.current?.focus()
  }, [busy])

  async function refreshMemories() {
    try {
      setMemories((await api.memories()).memories)
    } catch {
      /* the drawer is informational; a failure here must not disturb the conversation */
    }
  }

  async function send() {
    const text = draft.trim()
    if (!text || busy) return
    setBubbles((b) => [...b, { role: 'you', text }])
    setDraft('')
    setBusy(true)
    try {
      const res = await api.send(text)
      setBubbles((b) => [
        ...b,
        { role: 'them', text: res.reply, explanation: res.explanation, latency: res.latency_ms },
      ])
      setCtx(res.context)
      // Extraction runs in the background on the server, so the drawer lags one beat.
      setTimeout(refreshMemories, 1200)
    } catch (e) {
      setBubbles((b) => [...b, { role: 'them', text: `(${String(e)})` }])
    } finally {
      setBusy(false)
    }
  }

  async function startRollover() {
    setBusy(true)
    try {
      const res = await api.draftCapsule()
      setCapsule({ id: res.capsule_id, data: res.capsule })
    } finally {
      setBusy(false)
    }
  }

  async function confirmRollover() {
    if (!capsule) return
    setBusy(true)
    try {
      const res = await api.approveCapsule(capsule.id, capsule.data)
      setEpisode(res.episode)
      setBubbles([])
      setCapsule(null)
      setCtx(null)
    } finally {
      setBusy(false)
    }
  }

  const needsRollover = ctx && (ctx.stage === 'choose' || ctx.stage === 'block')

  return (
    <div className="grid h-full grid-cols-1 lg:grid-cols-[15rem_minmax(0,1fr)_19rem]">
      {/* Left rail: who you are talking to, and how full the conversation is. */}
      <aside className="hidden flex-col gap-6 border-r border-[var(--color-line)] px-5 py-6 lg:flex">
        <div>
          <h2 className="font-display text-2xl leading-none tracking-tight">
            {persona.display_name}
          </h2>
          <p className="mt-1.5 text-[11px] text-[var(--color-faint)]">
            {persona.adult_age} · {persona.pronouns}
            {(persona as { type?: string }).type && ` · ${(persona as { type?: string }).type}`}
          </p>
        </div>

        <div className="space-y-1.5">
          <p className="text-[11px] text-[var(--color-faint)]">episode {episode}</p>
          {ctx && <Meter fraction={ctx.fraction} stage={ctx.stage} />}
        </div>

        {persona.tics?.length > 0 && (
          <div>
            <p className="text-[11px] text-[var(--color-faint)]">how they talk</p>
            <ul className="mt-1.5 space-y-1">
              {persona.tics.map((t) => (
                <li key={t} className="text-[12px] leading-snug text-[var(--color-muted)]">
                  {t}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="mt-auto space-y-2">
          <p className="flex items-center gap-1.5 text-[11px] text-[var(--color-faint)]">
            <span className="size-1.5 rounded-full bg-emerald-500" />
            no cloud connection
          </p>
          {model && <p className="font-mono text-[11px] text-[var(--color-faint)]">{model}</p>}
        </div>
      </aside>

      {/* Centre: the conversation. */}
      <main className="flex min-h-0 flex-col overflow-x-hidden">
        <div className="flex-1 overflow-y-auto px-6 py-10">
          <div className="mx-auto max-w-2xl space-y-6">
            {bubbles.length === 0 && (
              <motion.p
                {...riseIn}
                className="max-w-md text-[15px] leading-relaxed text-[var(--color-faint)]"
              >
                {episode > 1
                  ? `Episode ${episode}. ${persona.display_name} remembers where you left it.`
                  : `Say something. ${persona.display_name} will not be helpful about it.`}
              </motion.p>
            )}

            <AnimatePresence initial={false}>
              {bubbles.map((b, i) => (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.24, ease }}
                  layout
                >
                  {b.role === 'you' ? (
                    <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-[var(--color-raised)]
                                  px-4 py-2.5 text-[15px] leading-relaxed">
                      {b.text}
                    </p>
                  ) : (
                    <div className="max-w-[92%]">
                      <p className="whitespace-pre-wrap text-[17px] leading-relaxed">{b.text}</p>
                      {b.explanation && (
                        <ReplyChips
                          explanation={b.explanation}
                          latency={b.latency}
                          open={openDrawer === i}
                          onToggle={() => setOpenDrawer(openDrawer === i ? null : i)}
                        />
                      )}
                    </div>
                  )}
                </motion.div>
              ))}
            </AnimatePresence>

            {busy && <Thinking />}
            <div ref={endRef} />
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-[var(--color-line)] px-6 py-4">
          <div className="mx-auto max-w-2xl">
            <AnimatePresence>
              {needsRollover && !capsule && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.24, ease }}
                  className="mb-3 overflow-hidden"
                >
                  <div className="flex items-center justify-between gap-4 rounded-lg border
                                  border-[var(--color-warm-dim)]/40 bg-[var(--color-warm-dim)]/10 px-4 py-3">
                    <p className="text-[13px] text-[var(--color-muted)]">
                      This conversation is nearly full. Carry it into a new one before it starts
                      forgetting.
                    </p>
                    <Button variant="ghost" onClick={startRollover}>
                      review
                    </Button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <textarea
              ref={inputRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void send()
                }
              }}
              rows={2}
              disabled={ctx?.stage === 'block'}
              placeholder={ctx?.stage === 'block' ? 'roll the conversation over first' : ''}
              className="w-full resize-none rounded-xl border border-[var(--color-line)]
                         bg-[var(--color-surface)] px-4 py-3 text-[15px] leading-relaxed outline-none
                         transition-colors placeholder:text-[var(--color-faint)]
                         focus:border-[var(--color-faint)] disabled:opacity-50"
            />
            <div className="mt-2.5 flex items-center gap-3">
              <Button onClick={send} disabled={!draft.trim() || busy || ctx?.stage === 'block'}>
                send
              </Button>
              <Chip tone="quiet">enter to send</Chip>
              {ctx && (
                <span className="ml-auto font-mono text-[11px] text-[var(--color-faint)]">
                  {ctx.used}/{ctx.cap}
                </span>
              )}
            </div>
          </div>
        </div>
      </main>

      {/* Right: what it remembers. */}
      <aside className="hidden flex-col gap-4 overflow-y-auto border-l border-[var(--color-line)]
                        px-5 py-6 lg:flex">
        <div className="flex items-baseline justify-between">
          <h3 className="text-[13px] text-[var(--color-muted)]">what it remembers</h3>
          <button
            onClick={refreshMemories}
            className="text-[11px] text-[var(--color-faint)] transition-colors
                       hover:text-[var(--color-muted)]"
          >
            refresh
          </button>
        </div>

        {memories.length === 0 && (
          <p className="text-[12px] leading-relaxed text-[var(--color-faint)]">
            Nothing yet. It records things you actually said, and every record points back at the
            message it came from.
          </p>
        )}

        <ul className="space-y-2">
          <AnimatePresence initial={false}>
            {memories.map((m, i) => (
              <motion.li
                key={m.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: 8 }}
                transition={{ duration: 0.2, ease, delay: Math.min(i * 0.03, 0.15) }}
                className="group rounded-lg border border-[var(--color-line)] px-3 py-2"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-[var(--color-faint)]">
                    {m.kind.replace('_', ' ')}
                  </span>
                  <button
                    onClick={() => api.forget(m.id).then(refreshMemories)}
                    className="text-[10px] text-[var(--color-faint)] opacity-0 transition-opacity
                               hover:text-[var(--color-warm)] group-hover:opacity-100"
                  >
                    forget
                  </button>
                </div>
                <p className="mt-0.5 text-[12px] leading-snug text-[var(--color-muted)]">
                  {m.subject} {m.predicate} <span className="text-[var(--color-text)]">{m.value}</span>
                </p>
                {m.sensitivity !== 'normal' && (
                  <span className="mt-1 inline-block text-[10px] text-[var(--color-warm-dim)]">
                    {m.sensitivity.replace('_', ' ')}
                  </span>
                )}
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      </aside>

      <AnimatePresence>
        {capsule && (
          <RolloverDialog
            capsule={capsule.data}
            onCancel={() => setCapsule(null)}
            onConfirm={confirmRollover}
            busy={busy}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

/** Three dots that breathe. The only always-on animation in the app, and it earns it by
 *  standing in for a reply that can take several seconds on a local model. */
function Thinking() {
  return (
    <div className="flex gap-1.5" aria-label="thinking">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="size-1.5 rounded-full bg-[var(--color-faint)]"
          animate={{ opacity: [0.25, 1, 0.25] }}
          transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.14, ease: 'easeInOut' }}
        />
      ))}
    </div>
  )
}

/** The "why this reply" affordance. Hidden by default so the conversation reads as a
 *  conversation; one click shows the memories and passages that actually shaped it. */
function ReplyChips({
  explanation,
  latency,
  open,
  onToggle,
}: {
  explanation: Explanation
  latency?: number
  open: boolean
  onToggle: () => void
}) {
  const { memories_used, sources_used, style_violations, attempts } = explanation
  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {memories_used.slice(0, 2).map((m) => (
          <Chip key={m.id} tone="warm" title={m.text}>
            remembered: {m.text.slice(0, 34)}
            {m.text.length > 34 ? '…' : ''}
          </Chip>
        ))}
        {attempts > 1 && <Chip tone="quiet">rewritten {attempts - 1}×</Chip>}
        <button
          onClick={onToggle}
          className="text-[11px] text-[var(--color-faint)] underline-offset-4
                     transition-colors hover:text-[var(--color-muted)] hover:underline"
        >
          {open ? 'hide' : 'why this reply'}
        </button>
      </div>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.22, ease }}
            className="overflow-hidden"
          >
            <Panel className="mt-2.5 space-y-3">
              <Detail label="memories used">
                {memories_used.length === 0
                  ? 'none'
                  : memories_used.map((m) => `${m.text} (${m.score})`).join(' · ')}
              </Detail>
              <Detail label="background reading">
                {sources_used.length === 0
                  ? 'none'
                  : sources_used.map((s) => s.title).join(' · ')}
              </Detail>
              {style_violations.length > 0 && (
                <Detail label="rejected for sounding like an assistant">
                  {style_violations.map((v) => `${v.rule}: ${v.why}`).join(' · ')}
                </Detail>
              )}
              {latency && (
                <Detail label="generated in">{(latency / 1000).toFixed(1)}s locally</Detail>
              )}
            </Panel>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-[var(--color-faint)]">{label}</p>
      <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--color-muted)]">{children}</p>
    </div>
  )
}

function RolloverDialog({
  capsule,
  onCancel,
  onConfirm,
  busy,
}: {
  capsule: Capsule
  onCancel: () => void
  onConfirm: () => void
  busy: boolean
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18, ease }}
      className="fixed inset-0 z-40 flex items-center justify-center bg-[var(--color-ink)]/80 p-6"
      onClick={onCancel}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.97, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.98, y: 4 }}
        transition={{ duration: 0.26, ease }}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-2xl border
                   border-[var(--color-line)] bg-[var(--color-surface)] p-6"
      >
        <h3 className="font-display text-xl tracking-tight">What carries over</h3>
        <p className="mt-1.5 text-[13px] leading-relaxed text-[var(--color-muted)]">
          Edit or delete anything here before it becomes the next conversation. What you remove is
          genuinely gone.
        </p>

        <div className="mt-5 space-y-4">
          <Detail label="what happened">{capsule.recent_summary || '—'}</Detail>
          {capsule.unresolved_tension && (
            <Detail label="still unresolved">{capsule.unresolved_tension}</Detail>
          )}
          {capsule.open_threads.length > 0 && (
            <Detail label="left hanging">{capsule.open_threads.join(' · ')}</Detail>
          )}
          {capsule.shared_moments.length > 0 && (
            <Detail label="would be strange to forget">
              {capsule.shared_moments.join(' · ')}
            </Detail>
          )}
          {capsule.carried_tics.length > 0 && (
            <Detail label="how they keep talking">{capsule.carried_tics.join(' · ')}</Detail>
          )}
          {capsule.excluded_memory_ids.length > 0 && (
            <Detail label="deliberately excluded">
              {capsule.excluded_memory_ids.length} sensitive record(s) stay behind
            </Detail>
          )}
        </div>

        <div className="mt-6 flex gap-3">
          <Button onClick={onConfirm} disabled={busy}>
            {busy ? 'carrying over…' : 'start the next one'}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            not yet
          </Button>
        </div>
      </motion.div>
    </motion.div>
  )
}
