import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { api, type MemoryRecord } from '../api'
import { Button, Chip, ease } from '../ui'

/**
 * Everything the system believes about you, with the receipts.
 *
 * The product's central promise is that memory is inspectable, correctable and yours.
 * That promise is only real if there is a screen where you can act on it, so this one is
 * deliberately blunt: every record shows its confidence, its sensitivity, and the message
 * it was drawn from, and every record can be corrected, locked or destroyed.
 *
 * Correcting does not overwrite. It writes a replacement that supersedes the original and
 * keeps the audit link, because the history of what a system believed about someone is
 * part of what they are owed. Forgetting, by contrast, is real deletion, and the button
 * says so rather than softening it.
 */

type Record = MemoryRecord & {
  created_at?: number
  sources?: { message_id: string; role: string; text: string }[]
}

export function Memories({ onClose }: { onClose: () => void }) {
  const [memories, setMemories] = useState<Record[]>([])
  const [threads, setThreads] = useState<{ id: string; title: string }[]>([])
  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [filter, setFilter] = useState<'all' | 'sensitive' | 'unconfirmed'>('all')

  async function load() {
    const res = await api.memories(true)
    setMemories(res.memories as Record[])
    setThreads(res.threads)
  }

  useEffect(() => {
    void load()
  }, [])

  async function save(id: string) {
    if (!draft.trim()) return
    setBusy(true)
    try {
      await api.correctMemory(id, draft.trim())
      setEditing(null)
      setDraft('')
      await load()
    } finally {
      setBusy(false)
    }
  }

  const shown = memories.filter((m) =>
    filter === 'all'
      ? true
      : filter === 'sensitive'
        ? m.sensitivity !== 'normal'
        : m.requires_confirmation === 1,
  )

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18, ease }}
      className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto
                 bg-[var(--color-ink)]/85 p-6"
      onClick={onClose}
    >
      <motion.div
        role="dialog"
        aria-label="What Ollie remembers"
        initial={{ opacity: 0, scale: 0.98, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.99, y: 4 }}
        transition={{ duration: 0.26, ease }}
        onClick={(e) => e.stopPropagation()}
        className="my-6 w-full max-w-3xl rounded-2xl border border-[var(--color-line)]
                   bg-[var(--color-surface)] p-6"
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="font-display text-xl tracking-tight">What Ollie remembers</h3>
            <p className="mt-1.5 max-w-[62ch] text-[13px] leading-relaxed
                          text-[var(--color-muted)]">
              Every record came from something you actually said, and shows the message it
              came from. Correcting keeps the original and supersedes it. Forgetting
              deletes it.
            </p>
          </div>
          <Button variant="ghost" onClick={onClose}>
            close
          </Button>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-1.5">
          {(['all', 'sensitive', 'unconfirmed'] as const).map((f) => (
            <Chip key={f} tone={filter === f ? 'warm' : 'quiet'} onClick={() => setFilter(f)}>
              {f}
              {f === 'all' && ` (${memories.length})`}
              {f === 'sensitive' &&
                ` (${memories.filter((m) => m.sensitivity !== 'normal').length})`}
              {f === 'unconfirmed' &&
                ` (${memories.filter((m) => m.requires_confirmation === 1).length})`}
            </Chip>
          ))}
        </div>

        {shown.length === 0 && (
          <p className="mt-6 text-[13px] text-[var(--color-faint)]">
            Nothing here yet. Records appear as you talk.
          </p>
        )}

        <ul className="mt-4 space-y-2">
          <AnimatePresence initial={false}>
            {shown.map((m) => (
              <motion.li
                key={m.id}
                layout
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: 12 }}
                transition={{ duration: 0.2, ease }}
                className="rounded-xl border border-[var(--color-line)] p-4"
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <Chip tone="quiet">{m.kind.replace(/_/g, ' ')}</Chip>
                  {m.sensitivity !== 'normal' && (
                    <Chip tone="warm">{m.sensitivity.replace(/_/g, ' ')}</Chip>
                  )}
                  {m.requires_confirmation === 1 && <Chip tone="quiet">inferred</Chip>}
                  {m.user_locked === 1 && <Chip tone="warm">locked</Chip>}
                  <span data-numeric className="ml-auto text-[11px] text-[var(--color-faint)]">
                    {Math.round(m.confidence * 100)}% sure
                  </span>
                </div>

                {editing === m.id ? (
                  <div className="mt-3">
                    <input
                      autoFocus
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void save(m.id)
                        if (e.key === 'Escape') setEditing(null)
                      }}
                      className="w-full rounded-lg border border-[var(--color-faint)]
                                 bg-[var(--color-ink)] px-3 py-2 text-[14px] outline-none"
                    />
                    <div className="mt-2 flex gap-2">
                      <Button onClick={() => save(m.id)} disabled={busy}>
                        {busy ? 'saving…' : 'correct it'}
                      </Button>
                      <Button variant="ghost" onClick={() => setEditing(null)}>
                        cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <p className="mt-2 text-[14px] leading-snug">
                    <span className="text-[var(--color-muted)]">
                      {m.subject} {m.predicate}{' '}
                    </span>
                    <span className="text-[var(--color-text)]">{m.value}</span>
                  </p>
                )}

                <div className="mt-3 flex flex-wrap items-center gap-3 text-[11px]">
                  {m.sources && m.sources.length > 0 && (
                    <button
                      onClick={() => setExpanded(expanded === m.id ? null : m.id)}
                      className="text-[var(--color-faint)] underline-offset-4
                                 transition-colors hover:text-[var(--color-muted)] hover:underline"
                    >
                      {expanded === m.id ? 'hide source' : 'where this came from'}
                    </button>
                  )}
                  {editing !== m.id && (
                    <button
                      onClick={() => {
                        setEditing(m.id)
                        setDraft(m.value)
                      }}
                      className="text-[var(--color-faint)] underline-offset-4
                                 transition-colors hover:text-[var(--color-muted)] hover:underline"
                    >
                      that&rsquo;s wrong
                    </button>
                  )}
                  <button
                    onClick={() => api.lock(m.id, m.user_locked !== 1).then(load)}
                    className="text-[var(--color-faint)] underline-offset-4
                               transition-colors hover:text-[var(--color-muted)] hover:underline"
                  >
                    {m.user_locked === 1 ? 'unlock' : 'keep this one'}
                  </button>
                  <button
                    onClick={() => api.forget(m.id).then(load)}
                    className="ml-auto text-[var(--color-faint)] underline-offset-4
                               transition-colors hover:text-[var(--color-warm)] hover:underline"
                  >
                    forget
                  </button>
                </div>

                <AnimatePresence>
                  {expanded === m.id && m.sources && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.22, ease }}
                      className="overflow-hidden"
                    >
                      <div className="mt-3 space-y-1.5 rounded-lg bg-[var(--color-ink)]/60 p-3">
                        {m.sources.map((s) => (
                          <p key={s.message_id} className="text-[12px] leading-relaxed">
                            <span className="text-[var(--color-faint)]">
                              {s.role === 'user' ? 'you' : 'them'}:{' '}
                            </span>
                            <span className="text-[var(--color-muted)]">{s.text}</span>
                          </p>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>

        {threads.length > 0 && (
          <section className="mt-6 border-t border-[var(--color-line)] pt-5">
            <p className="text-[11px] text-[var(--color-faint)]">
              still open between you
            </p>
            <ul className="mt-2 space-y-1">
              {threads.map((t) => (
                <li key={t.id} className="text-[13px] text-[var(--color-muted)]">
                  {t.title}
                </li>
              ))}
            </ul>
          </section>
        )}
      </motion.div>
    </motion.div>
  )
}
