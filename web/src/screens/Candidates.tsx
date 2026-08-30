import { motion } from 'motion/react'
import { useState } from 'react'
import { api, type Candidate, type Read } from '../api'
import type { Matching } from './Onboarding'
import { Button, Chip, Panel, riseIn } from '../ui'

export function Candidates({
  read,
  matching,
  candidates,
  onChosen,
}: {
  read: Read
  matching: Matching
  candidates: Candidate[]
  onChosen: (persona: Candidate) => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [showTypes, setShowTypes] = useState(false)

  async function choose(c: Candidate & { type?: string }) {
    setBusy(c.id)
    try {
      const res = await api.selectPersona(c.id)
      onChosen({ ...res.persona, ...c })
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-14">
      <motion.div {...riseIn}>
        <h2 className="text-2xl font-medium tracking-tight">Here&rsquo;s what came back</h2>
      </motion.div>

      <motion.div {...riseIn} transition={{ ...riseIn.transition, delay: 0.06 }} className="mt-6 grid gap-4 lg:grid-cols-2">
        <Panel title="what ollie made of you">
          <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-[var(--color-muted)]">
            {read.summary}
          </pre>
          {read.dodges.length > 0 && (
            <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[12px] text-[var(--color-faint)]">
              you steered around: {read.dodges.join('; ')}
            </p>
          )}
        </Panel>

        <Panel title="your type">
          <div className="flex items-baseline gap-3">
            <span className="font-mono text-2xl tracking-wider text-[var(--color-warm)]">
              {matching.user_type}
            </span>
            <Chip tone="quiet">{matching.user_type_source}</Chip>
          </div>
          <p className="mt-2 text-[13px] leading-relaxed text-[var(--color-muted)]">
            {matching.user_type_description}
          </p>

          <button
            onClick={() => setShowTypes((v) => !v)}
            className="mt-3 text-[12px] text-[var(--color-faint)] underline-offset-4 hover:underline"
          >
            {showTypes ? 'hide' : 'how all sixteen ranked'}
          </button>

          {showTypes && (
            <motion.div {...riseIn} className="mt-3 space-y-1">
              {matching.ranked.map((r) => (
                <div key={r.type} className="flex items-center gap-3 text-[12px]">
                  <span className="w-11 font-mono text-[var(--color-muted)]">{r.type}</span>
                  <div className="h-1 flex-1 overflow-hidden rounded-full bg-[var(--color-line)]/50">
                    <div
                      className="h-full rounded-full bg-[var(--color-warm-dim)]"
                      style={{ width: `${r.score * 100}%` }}
                    />
                  </div>
                  <span className="w-9 text-right font-mono text-[var(--color-faint)]">
                    {r.score.toFixed(2)}
                  </span>
                </div>
              ))}
              <p className="pt-2 text-[11px] leading-relaxed text-[var(--color-faint)]">
                {matching.basis}
              </p>
            </motion.div>
          )}
        </Panel>
      </motion.div>

      <h3 className="mt-10 text-[13px] font-medium uppercase tracking-[0.14em] text-[var(--color-faint)]">
        three people who would suit you
      </h3>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        {candidates.map((c, i) => {
          const typed = c as Candidate & {
            type?: string
            type_description?: string
            match_reason?: string
          }
          return (
            <motion.article
              key={c.id}
              {...riseIn}
              transition={{ ...riseIn.transition, delay: 0.08 + i * 0.06 }}
              whileHover={{ y: -3 }}
              className="flex flex-col rounded-xl border border-[var(--color-line)]
                         bg-[var(--color-surface)] p-5 transition-colors
                         hover:border-[var(--color-faint)]"
            >
              <header className="flex items-baseline justify-between gap-2">
                <h4 className="text-lg font-medium">{c.display_name}</h4>
                {typed.type && (
                  <span className="font-mono text-[11px] tracking-wider text-[var(--color-warm)]">
                    {typed.type}
                  </span>
                )}
              </header>
              <p className="mt-0.5 text-[12px] text-[var(--color-faint)]">
                {c.adult_age} · {c.pronouns}
              </p>

              {c.background && (
                <p className="mt-3 text-[13px] leading-relaxed text-[var(--color-muted)]">
                  {c.background}
                </p>
              )}

              <Field label="goes too long about">{c.special_interest}</Field>
              <Field label="how they argue">{c.pushback_style}</Field>
              <Field label="where you&rsquo;ll rub">{c.friction_points.join('; ')}</Field>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {c.stable_traits.slice(0, 4).map((t) => (
                  <Chip key={t}>{t}</Chip>
                ))}
              </div>

              {typed.match_reason && (
                <p className="mt-3 border-t border-[var(--color-line)] pt-3 text-[11px]
                              leading-relaxed text-[var(--color-faint)]">
                  {typed.match_reason}
                </p>
              )}

              <div className="mt-4 flex-1" />
              <Button onClick={() => choose(typed)} disabled={busy !== null} className="w-full">
                {busy === c.id ? 'starting…' : `start with ${c.display_name.split(' ')[0]}`}
              </Button>
            </motion.article>
          )
        })}
      </div>

      <p className="mt-6 max-w-2xl text-[12px] leading-relaxed text-[var(--color-faint)]">
        This is a heuristic from a book, not a verdict about your real romantic life. If none of
        them appeal, that is a reasonable reaction to three strangers.
      </p>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  if (!children) return null
  return (
    <div className="mt-3">
      <p className="text-[11px] uppercase tracking-[0.1em] text-[var(--color-faint)]">{label}</p>
      <p className="mt-0.5 text-[13px] leading-relaxed text-[var(--color-muted)]">{children}</p>
    </div>
  )
}
