import { motion } from 'motion/react'
import { ease } from './ui'

/**
 * The six interaction-state variables, made visible.
 *
 * Two rules govern how this is presented. It must never read as a score the user is
 * trying to maximise, so there is no total, no percentage and no upward arrow; and it must
 * never claim the character has feelings, so the heading says what it is. The one-line
 * reading exists because six numbers are not how a person describes how an evening is
 * going, and the numbers underneath are there for anyone who wants to check the reading
 * against them.
 */

export type InteractionState = Record<string, number | string | boolean>

const DIMENSIONS: { key: string; label: string }[] = [
  { key: 'warmth', label: 'warmth' },
  { key: 'trust', label: 'trust' },
  { key: 'playfulness', label: 'play' },
  { key: 'emotional_depth', label: 'depth' },
  { key: 'romantic_tension', label: 'charge' },
  { key: 'conflict_tension', label: 'friction' },
]

/** Turn the numbers into the sentence a person would actually say. */
function reading(state: InteractionState): string {
  const n = (k: string) => (typeof state[k] === 'number' ? (state[k] as number) : 0)
  const parts: string[] = []

  if (n('conflict_tension') > 0.25) parts.push('still a bit prickly')
  else if (n('warmth') > 0.6 && n('playfulness') > 0.55) parts.push('warm and playing')
  else if (n('warmth') > 0.6) parts.push('warm')
  else if (n('warmth') < 0.35) parts.push('holding back')
  else parts.push('somewhere in the middle')

  if (n('emotional_depth') > 0.55) parts.push('past small talk')
  if (n('romantic_tension') > 0.5) parts.push('there is a charge')
  if (n('trust') > 0.6) parts.push('trusting you')
  else if (n('trust') < 0.3) parts.push('not sure about you yet')

  return parts.slice(0, 3).join(', ')
}

export function StateDial({
  state,
  delta,
}: {
  state: InteractionState
  delta?: Record<string, number>
}) {
  const values = DIMENSIONS.filter(({ key }) => typeof state[key] === 'number')
  if (values.length === 0) return null

  const stage = typeof state.stage === 'string' ? state.stage : null

  return (
    <div className="space-y-2.5">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[11px] text-[var(--color-faint)]">how it is going</p>
        {stage && (
          <p className="text-[11px] text-[var(--color-faint)]">{stage.replace(/_/g, ' ')}</p>
        )}
      </div>

      <p className="text-[12px] leading-snug text-[var(--color-muted)]">{reading(state)}</p>

      <div className="space-y-1.5 pt-0.5">
        {values.map(({ key, label }) => {
          const value = state[key] as number
          const moved = delta?.[key] ?? 0
          return (
            <div key={key} className="flex items-center gap-2">
              <span className="w-[3.75rem] shrink-0 text-[10px] text-[var(--color-faint)]">
                {label}
              </span>
              <div className="h-[3px] flex-1 overflow-hidden rounded-full bg-[var(--color-line)]/60">
                {/* scaleX rather than width: width animates layout, scaleX stays on the
                    compositor. transform-origin left makes it grow from the label. */}
                <motion.div
                  className="h-full w-full origin-left rounded-full"
                  style={{
                    background:
                      key === 'conflict_tension'
                        ? 'var(--color-warm-dim)'
                        : 'var(--color-faint)',
                  }}
                  initial={false}
                  animate={{ scaleX: Math.max(0.02, Math.min(1, value)) }}
                  transition={{ duration: 0.5, ease }}
                />
              </div>
              {/* The delta is the point. A number that moved a little after the last
                  message is the whole argument that the character responds rather than
                  resets. It fades out on the next turn that does not move it. */}
              <span
                data-numeric
                className={`w-8 shrink-0 text-right text-[10px] tabular-nums transition-opacity
                  duration-500 ${Math.abs(moved) > 0.001 ? 'opacity-100' : 'opacity-0'}`}
                style={{
                  color: moved > 0 ? 'var(--color-warm)' : 'var(--color-faint)',
                }}
              >
                {moved > 0 ? '+' : ''}
                {moved.toFixed(2)}
              </span>
            </div>
          )
        })}
      </div>

      <p className="pt-0.5 text-[10px] leading-snug text-[var(--color-faint)]">
        Simulation state, not feelings. It moves by at most 0.05 a message.
      </p>
    </div>
  )
}
