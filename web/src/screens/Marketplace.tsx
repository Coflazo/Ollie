import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { Button, Chip, ease } from '../ui'

/**
 * The simulated research contribution.
 *
 * Nothing here sends anything. The buyer is invented, the quote is a deterministic
 * function of turn count and risk, and every artifact the backend writes carries a banner
 * saying so. The screen exists to make an argument the product could not make in prose:
 * that the user's conversation has value, that they should see exactly what would leave
 * before deciding, and that a local redaction pass is pseudonymisation rather than
 * anonymisation.
 *
 * That last point is why the risk panel is not a green tick. Removing names from a
 * romantic conversation does not make it anonymous, and this screen refuses to imply
 * otherwise even though it would look better if it did.
 */

type Preview = {
  simulation: boolean
  uploaded: boolean
  paid: boolean
  buyer: string
  banner: string
  purpose: string
  turn_count: number
  removed_by_kind: Record<string, number>
  excluded_special_category: number
  sample: { role: string; text: string; removed: number }[]
  linkability: {
    score: number
    level: 'low' | 'medium' | 'high'
    quasi_identifiers: { kind: string; text: string }[]
    residual_direct: { kind: string; text: string }[]
    note: string
  }
  quote_eur: number
}

export function Marketplace({ onClose }: { onClose: () => void }) {
  const [preview, setPreview] = useState<Preview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [receipt, setReceipt] = useState<{ receipt_id: string; path: string } | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .marketPreview()
      .then((p) => setPreview(p as unknown as Preview))
      .catch((e) => setError(String(e)))
  }, [])

  async function accept() {
    if (!preview) return
    setBusy(true)
    try {
      setReceipt(await api.marketAccept(preview as unknown as Record<string, unknown>))
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const risk = preview?.linkability
  const riskColour =
    risk?.level === 'high'
      ? 'var(--color-warm)'
      : risk?.level === 'medium'
        ? 'var(--color-warm-dim)'
        : 'var(--color-faint)'

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18, ease }}
      className="fixed inset-0 z-40 flex items-center justify-center bg-[var(--color-ink)]/85 p-6"
      onClick={onClose}
    >
      <motion.div
        role="dialog"
        aria-label="Simulated research contribution"
        initial={{ opacity: 0, scale: 0.97, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.98, y: 4 }}
        transition={{ duration: 0.26, ease }}
        onClick={(e) => e.stopPropagation()}
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl border
                   border-[var(--color-line)] bg-[var(--color-surface)] p-6"
      >
        {/* The disclaimer leads. Anything less prominent and a screenshot of this screen
            would be a claim we are not making. */}
        <div className="rounded-lg border border-[var(--color-warm-dim)]/40
                        bg-[var(--color-warm-dim)]/10 px-4 py-3">
          <p className="font-mono text-[11px] leading-relaxed tracking-wide text-[var(--color-warm)]">
            SIMULATION. NOTHING IS SENT, NOTHING IS PAID, AND NO REAL COMPANY IS INVOLVED.
          </p>
        </div>

        <h3 className="mt-5 font-display text-xl tracking-tight">
          What a research contribution would actually contain
        </h3>
        <p className="mt-1.5 max-w-[62ch] text-[13px] leading-relaxed text-[var(--color-muted)]">
          If this conversation were ever offered to a research buyer, this is what would leave
          and what would stay. Everything below was computed on this machine.
        </p>

        {error && <p className="mt-4 text-[13px] text-[var(--color-warm)]">{error}</p>}
        {!preview && !error && (
          <p className="mt-6 text-[13px] text-[var(--color-faint)]">redacting locally…</p>
        )}

        {preview && (
          <div className="mt-6 space-y-6">
            <section>
              <Label>purpose, and nothing outside it</Label>
              <p className="mt-1 text-[13px] text-[var(--color-muted)]">{preview.purpose}</p>
            </section>

            <section>
              <Label>identifiers removed</Label>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {Object.entries(preview.removed_by_kind).length === 0 ? (
                  <span className="text-[13px] text-[var(--color-faint)]">
                    none found in this conversation
                  </span>
                ) : (
                  Object.entries(preview.removed_by_kind).map(([kind, n]) => (
                    <Chip key={kind} tone="neutral">
                      {kind.replace(/_/g, ' ')} ×{n}
                    </Chip>
                  ))
                )}
                {preview.excluded_special_category > 0 && (
                  <Chip tone="warm">
                    {preview.excluded_special_category} sensitive record(s) excluded entirely
                  </Chip>
                )}
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-[var(--color-faint)]">
                Special-category records are excluded rather than redacted. Redacting a
                sentence about someone&rsquo;s sexuality still leaves a sentence about
                someone&rsquo;s sexuality.
              </p>
            </section>

            <section>
              <Label>exactly what would leave</Label>
              <div className="mt-2 space-y-2 rounded-lg border border-[var(--color-line)]
                              bg-[var(--color-ink)]/50 p-3">
                {preview.sample.map((m, i) => (
                  <p key={i} className="text-[12px] leading-relaxed">
                    <span className="text-[var(--color-faint)]">
                      {m.role === 'user' ? 'you' : 'them'}:{' '}
                    </span>
                    <span className="text-[var(--color-muted)]">{m.text}</span>
                  </p>
                ))}
                {preview.turn_count > preview.sample.length && (
                  <p className="text-[11px] text-[var(--color-faint)]">
                    and {preview.turn_count - preview.sample.length} more of{' '}
                    {preview.turn_count} turns
                  </p>
                )}
              </div>
            </section>

            {risk && (
              <section>
                <Label>how identifiable this still is</Label>
                <div className="mt-2 flex items-center gap-3">
                  <div className="h-1 flex-1 overflow-hidden rounded-full bg-[var(--color-line)]/60">
                    <motion.div
                      className="h-full w-full origin-left rounded-full"
                      style={{ background: riskColour }}
                      initial={false}
                      animate={{ scaleX: Math.max(0.03, risk.score) }}
                      transition={{ duration: 0.5, ease }}
                    />
                  </div>
                  <span className="text-[12px]" style={{ color: riskColour }}>
                    {risk.level}
                  </span>
                </div>

                {risk.quasi_identifiers.length > 0 && (
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {risk.quasi_identifiers.slice(0, 8).map((q, i) => (
                      <Chip key={i} tone="quiet" title={q.text}>
                        {q.kind.replace(/_/g, ' ')}
                      </Chip>
                    ))}
                  </div>
                )}

                <p className="mt-2.5 max-w-[62ch] text-[11px] leading-relaxed
                              text-[var(--color-faint)]">
                  {risk.note}
                </p>
              </section>
            )}

            <section className="border-t border-[var(--color-line)] pt-5">
              <div className="flex items-end justify-between gap-4">
                <div>
                  <Label>what {preview.buyer} would offer</Label>
                  <p className="mt-1 text-[11px] text-[var(--color-faint)]">
                    A fictional buyer. The figure is a deterministic function of turn count,
                    languages and risk, capped low on purpose: it illustrates an incentive
                    model rather than a market price.
                  </p>
                </div>
                <p data-numeric className="shrink-0 font-display text-3xl tracking-tight">
                  &euro;{preview.quote_eur.toFixed(2)}
                </p>
              </div>
            </section>

            <AnimatePresence mode="wait">
              {receipt ? (
                <motion.div
                  key="receipt"
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.24, ease }}
                  className="rounded-lg border border-[var(--color-line)] p-4"
                >
                  <p className="text-[13px] text-[var(--color-text)]">
                    Receipt written locally. Still nothing sent and nothing paid.
                  </p>
                  <p className="mt-1.5 break-all font-mono text-[11px] text-[var(--color-faint)]">
                    {receipt.path}
                  </p>
                  <div className="mt-4">
                    <Button variant="ghost" onClick={onClose}>
                      done
                    </Button>
                  </div>
                </motion.div>
              ) : (
                <motion.div key="actions" className="flex flex-wrap items-center gap-3">
                  {/* Keeping private is the primary action. A consent screen where the
                      agreeable button is the prettiest one is not a consent screen. */}
                  <Button onClick={onClose}>keep it private</Button>
                  <Button variant="ghost" onClick={accept} disabled={busy}>
                    {busy ? 'writing receipt…' : 'simulate contributing it'}
                  </Button>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}
      </motion.div>
    </motion.div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] text-[var(--color-faint)]">{children}</p>
}
