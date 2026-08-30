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
import { StateDial, type InteractionState } from '../StateDial'
import { Button, Chip, Meter, Panel, Thinking, Waiting, ease, riseIn } from '../ui'
import { Marketplace } from './Marketplace'
import { Memories } from './Memories'

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
  const [state, setState] = useState<InteractionState | null>(null)
  const [delta, setDelta] = useState<Record<string, number>>({})
  const [market, setMarket] = useState(false)
  const [manager, setManager] = useState(false)
  // Focus mode collapses both instrument panels so the conversation is alone on screen.
  // Off by default: the rails are how a first run learns that the product keeps receipts,
  // and hiding them would bury the provenance this whole design argues for. Focus is for
  // once you are actually talking, so the choice is remembered.
  const [focus, setFocus] = useState(() => {
    try {
      return localStorage.getItem('ollie.focus') === '1'
    } catch {
      return false
    }
  })
  function toggleFocus() {
    // The write stays out of the updater: React may call an updater more than once, and a
    // state function that touches storage is the kind of impurity StrictMode exists to find.
    const next = !focus
    setFocus(next)
    try {
      localStorage.setItem('ollie.focus', next ? '1' : '')
    } catch {
      /* private browsing; the mode still works for this session */
    }
  }

  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [bubbles.length, busy])

  useEffect(() => {
    if (!busy) inputRef.current?.focus()
  }, [busy])

  // A resumed conversation has to look resumed straight away: the transcript, what it
  // remembers, and the state it was left in. Without this, software that claims to
  // remember you opens on an empty screen, which is the wrong first impression.
  useEffect(() => {
    void (async () => {
      try {
        const [c, h] = await Promise.all([api.context(), api.history()])
        setCtx(c)
        if (c.state) setState(c.state)
        setEpisode(c.episode ?? h.episode)
        setBubbles(
          h.messages.map((m) => ({
            role: m.role === 'user' ? ('you' as const) : ('them' as const),
            text: m.content,
          })),
        )
      } catch {
        /* a fresh session has no history; that is not an error */
      }
      await refreshMemories()
    })()
  }, [])

  async function refreshMemories() {
    try {
      setMemories((await api.memories()).memories)
    } catch {
      /* the drawer is informational; a failure here must not disturb the conversation */
    }
  }

  /** Extraction runs server-side after the reply is already on screen, so the updated
   *  state and its delta arrive a beat later than the message does. */
  async function refreshAfterTurn() {
    await refreshMemories()
    try {
      const c = await api.context()
      setCtx(c)
      if (c.consolidation?.state) setState(c.consolidation.state)
      else if (c.state) setState(c.state)
      setDelta(c.consolidation?.delta ?? {})
    } catch {
      /* same: informational */
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
      if (res.state) setState(res.state)
      // Extraction runs in the background on the server, so the drawer lags one beat.
      setTimeout(refreshAfterTurn, 1200)
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

  // Takes the capsule the user actually edited, not the one the model drafted. The approve
  // endpoint reads this object for the carried state, the episode card and the text episode
  // two opens with, so a line deleted in the dialog never reaches the next conversation.
  async function confirmRollover(edited: Capsule) {
    if (!capsule) return
    setBusy(true)
    try {
      const res = await api.approveCapsule(capsule.id, edited)
      setEpisode(res.episode)
      setBubbles([])
      setCapsule(null)
      setCtx(null)
      // The next session starts from the capsule's state, so the dial carries the mood
      // across the rollover instead of snapping back to the defaults.
      if (edited.interaction_state) setState(edited.interaction_state)
    } finally {
      setBusy(false)
    }
  }

  const needsRollover = ctx && (ctx.stage === 'choose' || ctx.stage === 'block')

  return (
    <div
      className={`grid h-full grid-cols-1 ${
        focus ? '' : 'lg:grid-cols-[15rem_minmax(0,1fr)_19rem]'
      }`}
    >
      {/* Left rail: who you are talking to, and how full the conversation is. */}
      <aside
        className={`flex-col gap-6 border-r border-[var(--color-line)] px-5 py-6 ${
          focus ? 'hidden' : 'hidden lg:flex'
        }`}
      >
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

        {state && <StateDial state={state} delta={delta} />}

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
          <button
            onClick={() => setManager(true)}
            className="text-left text-[11px] text-[var(--color-faint)] underline-offset-4
                       transition-colors hover:text-[var(--color-muted)] hover:underline"
          >
            manage what it remembers
          </button>
          <button
            onClick={() => setMarket(true)}
            className="text-left text-[11px] text-[var(--color-faint)] underline-offset-4
                       transition-colors hover:text-[var(--color-muted)] hover:underline"
          >
            what this conversation is worth
          </button>
          <button
            onClick={toggleFocus}
            className="text-left text-[11px] text-[var(--color-faint)] underline-offset-4
                       transition-colors hover:text-[var(--color-muted)] hover:underline"
          >
            just the conversation
          </button>
        </div>
      </aside>

      {/* Centre: the conversation. */}
      <main className="flex min-h-0 flex-col overflow-x-hidden">
        {focus && (
          <div className="flex items-center gap-4 border-b border-[var(--color-line)] px-6 py-2">
            <span className="text-[12px] text-[var(--color-muted)]">{persona.display_name}</span>
            <span data-numeric className="text-[11px] text-[var(--color-faint)]">
              episode {episode}
            </span>
            {ctx && (
              <div className="w-44">
                <Meter fraction={ctx.fraction} stage={ctx.stage} />
              </div>
            )}
            {/* Below lg the rails are already hidden, so leaving focus mode there would
                take this strip away and give nothing back, including the only control
                that returns it. The way out is offered where there is something to go to. */}
            <button
              onClick={toggleFocus}
              className="ml-auto hidden text-[11px] text-[var(--color-faint)] underline-offset-4
                         transition-colors hover:text-[var(--color-muted)] hover:underline
                         lg:block"
            >
              show the panels
            </button>
          </div>
        )}
        <div className="flex-1 overflow-y-auto px-6 py-10">
          <div className="mx-auto max-w-[44rem] space-y-8">
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
                    <div className="group/reply max-w-[92%]">
                      <p className="whitespace-pre-wrap text-[17px] leading-[1.7]">{b.text}</p>
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

            {busy && (
              <div className="flex items-center gap-2.5">
                <Thinking />
                <span className="text-[12px] text-[var(--color-faint)]">
                  {persona.display_name.split(' ')[0]} is typing
                </span>
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-[var(--color-line)] px-6 py-4">
          <div className="mx-auto max-w-[44rem]">
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
                    {/* Drafting the capsule measured at 47s. Leaving the same sentence on
                        screen with a dead button was the longest unexplained pause in the
                        product, and it sits on the path the demo is judged on. */}
                    {busy ? (
                      <Waiting
                        label="reading the conversation back"
                        hint="deciding what carries over and what stays behind. you get to
                              edit it before anything is kept."
                      />
                    ) : (
                      <>
                        <p className="text-[13px] text-[var(--color-muted)]">
                          This conversation is nearly full. Carry it into a new one before it
                          starts forgetting.
                        </p>
                        <Button variant="ghost" onClick={startRollover}>
                          review
                        </Button>
                      </>
                    )}
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
                         bg-[var(--color-surface)] px-4 py-3 text-[16px] leading-relaxed outline-none
                         transition-colors placeholder:text-[var(--color-faint)]
                         focus:border-[var(--color-warm-dim)] disabled:opacity-50"
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
      <aside
        className={`flex-col gap-4 overflow-y-auto border-l border-[var(--color-line)] px-5 py-6 ${
          focus ? 'hidden' : 'hidden lg:flex'
        }`}
      >
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

      <AnimatePresence>{market && <Marketplace onClose={() => setMarket(false)} />}</AnimatePresence>
      <AnimatePresence>
        {manager && (
          <Memories
            onClose={() => {
              setManager(false)
              void refreshMemories()
            }}
          />
        )}
      </AnimatePresence>

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
    // Receded at rest so the conversation reads as a conversation, not an audit log.
    // Hover on the reply or keyboard focus brings it back, and an open drawer holds it.
    // 55% is deliberate: 35% measured at 1.38:1 against the ink, which is invisible, and a
    // provenance chip nobody notices exist is indistinguishable from no provenance at all.
    <div
      className={`mt-2 transition-opacity duration-200 focus-within:opacity-100 ${
        open ? 'opacity-100' : 'opacity-55 group-hover/reply:opacity-100'
      }`}
    >
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

/** A line of the capsule the user can actually rewrite.
 *
 *  Borderless at rest so the dialog still reads as prose, this is the artifact you read
 *  out loud during the demo: and it only shows its edges once you are in it. */
function EditableLine({
  label,
  value,
  onChange,
  onRemove,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  onRemove?: () => void
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[10px] uppercase tracking-wider text-[var(--color-faint)]">{label}</p>
        {onRemove && (
          <button
            onClick={onRemove}
            className="text-[10px] text-[var(--color-faint)] transition-colors
                       hover:text-[var(--color-warm)]"
          >
            remove
          </button>
        )}
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={Math.min(6, Math.max(2, Math.ceil(value.length / 58)))}
        className="mt-0.5 w-full resize-y rounded-md border border-transparent bg-transparent
                   px-2 py-1 text-[12px] leading-relaxed text-[var(--color-muted)] outline-none
                   transition-colors hover:border-[var(--color-line)]
                   focus:border-[var(--color-faint)] focus:text-[var(--color-text)]"
      />
    </div>
  )
}

/** The list fields. Each entry can be edited in place or deleted outright; deleting is the
 *  whole point, since the dialog promises that what you remove is genuinely gone. */
function EditableList({
  label,
  items,
  onChange,
}: {
  label: string
  items: string[]
  onChange: (v: string[]) => void
}) {
  if (items.length === 0) return null
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wider text-[var(--color-faint)]">{label}</p>
      <ul className="mt-1 space-y-1">
        <AnimatePresence initial={false}>
          {items.map((item, i) => (
            <motion.li
              key={i}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.16, ease }}
              className="group flex items-start gap-2 overflow-hidden"
            >
              <input
                value={item}
                onChange={(e) => onChange(items.map((v, j) => (j === i ? e.target.value : v)))}
                className="min-w-0 flex-1 rounded-md border border-transparent bg-transparent
                           px-2 py-1 text-[12px] leading-relaxed text-[var(--color-muted)]
                           outline-none transition-colors hover:border-[var(--color-line)]
                           focus:border-[var(--color-faint)] focus:text-[var(--color-text)]"
              />
              <button
                onClick={() => onChange(items.filter((_, j) => j !== i))}
                aria-label={`remove "${item.slice(0, 40)}"`}
                className="mt-1 shrink-0 px-1 text-[11px] text-[var(--color-faint)] opacity-0
                           transition-opacity hover:text-[var(--color-warm)]
                           focus-visible:opacity-100 group-hover:opacity-100"
              >
                ×
              </button>
            </motion.li>
          ))}
        </AnimatePresence>
      </ul>
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
  onConfirm: (edited: Capsule) => void
  busy: boolean
}) {
  // Seeded once from the model's draft. Everything below edits this copy, and this copy is
  // what gets sent, so the promise in the paragraph above is the actual behaviour.
  const [draft, setDraft] = useState<Capsule>(capsule)
  const set = <K extends keyof Capsule>(key: K, value: Capsule[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

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
          <EditableLine
            label="what happened"
            value={draft.recent_summary}
            onChange={(v) => set('recent_summary', v)}
          />
          {draft.unresolved_tension !== null && draft.unresolved_tension !== undefined && (
            <EditableLine
              label="still unresolved"
              value={draft.unresolved_tension}
              onChange={(v) => set('unresolved_tension', v)}
              onRemove={() => set('unresolved_tension', null)}
            />
          )}
          <EditableList
            label="left hanging"
            items={draft.open_threads}
            onChange={(v) => set('open_threads', v)}
          />
          <EditableList
            label="would be strange to forget"
            items={draft.shared_moments}
            onChange={(v) => set('shared_moments', v)}
          />
          <EditableList
            label="how they keep talking"
            items={draft.carried_tics}
            onChange={(v) => set('carried_tics', v)}
          />
          {draft.excluded_memory_ids.length > 0 && (
            // Not editable: these are the sensitive records being held back. The control for
            // those is the memory panel, where the provenance chain is visible.
            <Detail label="deliberately excluded">
              {draft.excluded_memory_ids.length} sensitive record(s) stay behind
            </Detail>
          )}
        </div>

        <div className="mt-6 flex gap-3">
          <Button onClick={() => onConfirm(draft)} disabled={busy}>
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
