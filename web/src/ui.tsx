import { motion } from 'motion/react'
import { useEffect, useState, type ReactNode } from 'react'

/** Expo-out. The built-in `ease-out` keyword is too weak to read as intentional, and
 *  `ease-in` is banned outright: it delays the first frame, which is exactly the moment
 *  the user is watching. */
export const ease = [0.16, 1, 0.3, 1] as const

/** Entrances are short. Anything past ~250ms in a chat reads as lag, not polish, and
 *  everything here moves transform and opacity only so it stays on the GPU. */
export const riseIn = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.24, ease },
}

/** Exits are faster than entrances. Waiting for something to leave feels like lag;
 *  waiting for something to arrive feels like anticipation. */
export const exitFast = { duration: 0.16, ease }

export function Chip({
  children,
  tone = 'neutral',
  onClick,
  title,
}: {
  children: ReactNode
  tone?: 'neutral' | 'warm' | 'quiet'
  onClick?: () => void
  title?: string
}) {
  const tones = {
    neutral: 'bg-[var(--color-raised)] text-[var(--color-muted)] border-[var(--color-line)]',
    warm: 'bg-[var(--color-warm-dim)]/20 text-[var(--color-warm)] border-[var(--color-warm-dim)]/40',
    quiet: 'bg-transparent text-[var(--color-faint)] border-[var(--color-line)]',
  }
  const Tag = onClick ? 'button' : 'span'
  return (
    <Tag
      onClick={onClick}
      title={title}
      // min-h-6 keeps interactive chips at the 24px desktop hit-target floor.
      className={`inline-flex min-h-6 items-center gap-1.5 rounded-full border px-2.5 py-1
        text-[11px] leading-none tracking-wide ${tones[tone]}
        ${onClick ? 'cursor-pointer transition-colors duration-150 hover:text-[var(--color-text)]' : ''}`}
    >
      {children}
    </Tag>
  )
}

export function Meter({ fraction, stage }: { fraction: number; stage: string }) {
  // A fuel gauge for the context window, not a score to maximise. It stays grey until it
  // matters, and the stage is spelled out in words so the colour is never load-bearing.
  const urgent = stage === 'block' || stage === 'choose'
  const colour = urgent
    ? 'var(--color-warm)'
    : stage === 'draft'
      ? 'var(--color-warm-dim)'
      : 'var(--color-line)'
  const label =
    stage === 'block'
      ? 'full, carry it over'
      : stage === 'choose'
        ? 'nearly full'
        : stage === 'draft'
          ? 'filling up'
          : 'plenty of room'

  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2 text-[11px]">
        <span className="text-[var(--color-faint)]">{label}</span>
        <span data-numeric className="text-[var(--color-faint)]">
          {Math.round(fraction * 100)}%
        </span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-[var(--color-line)]/50">
        <motion.div
          className="h-full rounded-full"
          style={{ background: colour }}
          animate={{ width: `${Math.min(100, fraction * 100)}%` }}
          transition={{ duration: 0.45, ease }}
        />
      </div>
    </div>
  )
}

/** Three dots that breathe. The only always-on animation in the app, and it earns it by
 *  standing in for a reply that can take several seconds on a local model. */
export function Thinking({ className = '' }: { className?: string }) {
  return (
    <div className={`flex gap-1.5 ${className}`} aria-label="working" role="status">
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

/** A wait with something said about it.
 *
 *  Local inference is slow and wildly uneven: four interview turns land in under two
 *  seconds each and the fifth takes eighty, because that one also extracts your traits and
 *  writes three people. Identical silence for both is what makes the long one read as a
 *  crash — the honest fix is to say which wait this is.
 *
 *  The elapsed count appears only once a wait has gone on long enough to worry about, so
 *  fast steps stay quiet. It is a sign of life, not a progress bar: nothing here can
 *  predict when a local model will finish, and a bar that pretends otherwise would be a
 *  worse lie than saying nothing.
 */
export function Waiting({
  label,
  hint,
  className = '',
}: {
  label: string
  hint?: string
  className?: string
}) {
  const [elapsed, setElapsed] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className={`flex items-start gap-2.5 ${className}`}>
      <Thinking className="mt-1.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-[13px] leading-snug text-[var(--color-muted)]">
          {label}
          {elapsed >= 4 && (
            <span data-numeric className="ml-1.5 text-[var(--color-faint)]">
              {elapsed}s
            </span>
          )}
        </p>
        {hint && elapsed >= 3 && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3, ease }}
            className="mt-1 text-[11px] leading-snug text-[var(--color-faint)]"
          >
            {hint}
          </motion.p>
        )}
      </div>
    </div>
  )
}

export function Panel({
  title,
  children,
  className = '',
}: {
  title?: string
  children: ReactNode
  className?: string
}) {
  return (
    // Semi-transparent border reads cleaner against the surface than a solid line, and
    // the radius stays at 12px so nested children can be concentric inside it.
    <section
      className={`rounded-xl border border-[var(--color-line)]/80 bg-[var(--color-surface)] p-4 ${className}`}
    >
      {title && <h3 className="mb-3 text-[12px] text-[var(--color-faint)]">{title}</h3>}
      {children}
    </section>
  )
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  disabled,
  className = '',
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'ghost' | 'danger'
  disabled?: boolean
  className?: string
  type?: 'button' | 'submit'
}) {
  // Every variant states its own text colour explicitly. Inheriting it is how buttons end
  // up with invisible labels on a background that changed underneath them.
  const variants = {
    primary:
      'bg-[var(--color-warm)] text-[#1a0e08] font-medium hover:bg-[#f2916c] active:bg-[#d9744e]',
    ghost:
      'border border-[var(--color-line)] text-[var(--color-muted)] hover:text-[var(--color-text)] hover:border-[var(--color-faint)]',
    danger:
      'border border-[var(--color-warm-dim)]/50 text-[var(--color-warm)] hover:bg-[var(--color-warm-dim)]/12 hover:border-[var(--color-warm-dim)]',
  }
  return (
    <motion.button
      type={type}
      // Instant press feedback. The interface confirms it heard you before the model has.
      whileTap={disabled ? undefined : { scale: 0.97 }}
      transition={{ duration: 0.12, ease }}
      onClick={onClick}
      disabled={disabled}
      className={`min-h-9 rounded-lg px-4 py-2 text-sm transition-colors duration-150
        disabled:cursor-not-allowed disabled:opacity-40 ${variants[variant]} ${className}`}
    >
      {children}
    </motion.button>
  )
}
