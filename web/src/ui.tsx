import { motion } from 'motion/react'
import type { ReactNode } from 'react'

// Entrances ease out and are short. Anything longer than ~300ms in a chat reads as lag
// rather than polish, and everything here animates transform/opacity only.
export const rise = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.22, ease: [0.22, 1, 0.36, 1] as const },
}

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
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]
        leading-none tracking-wide ${tones[tone]}
        ${onClick ? 'cursor-pointer transition-colors hover:text-[var(--color-text)]' : ''}`}
    >
      {children}
    </Tag>
  )
}

export function Meter({ fraction, stage }: { fraction: number; stage: string }) {
  // Deliberately not a score the user is invited to maximise — it is a fuel gauge for
  // the context window, and it only earns attention once it matters.
  const colour =
    stage === 'block' || stage === 'choose'
      ? 'var(--color-warm)'
      : stage === 'draft'
        ? 'var(--color-warm-dim)'
        : 'var(--color-line)'
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between text-[11px] text-[var(--color-faint)]">
        <span>memory of this conversation</span>
        <span className="font-mono">{Math.round(fraction * 100)}%</span>
      </div>
      <div className="h-1 w-full overflow-hidden rounded-full bg-[var(--color-line)]/50">
        <motion.div
          className="h-full rounded-full"
          style={{ background: colour }}
          animate={{ width: `${Math.min(100, fraction * 100)}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        />
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
    <section
      className={`rounded-xl border border-[var(--color-line)] bg-[var(--color-surface)] p-4 ${className}`}
    >
      {title && (
        <h3 className="mb-3 text-[11px] font-medium uppercase tracking-[0.14em] text-[var(--color-faint)]">
          {title}
        </h3>
      )}
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
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'ghost' | 'danger'
  disabled?: boolean
  className?: string
}) {
  const variants = {
    primary:
      'bg-[var(--color-warm)] text-[var(--color-ink)] hover:bg-[var(--color-warm)]/90 font-medium',
    ghost:
      'border border-[var(--color-line)] text-[var(--color-muted)] hover:text-[var(--color-text)] hover:border-[var(--color-faint)]',
    danger: 'border border-[var(--color-warm-dim)]/40 text-[var(--color-warm)] hover:bg-[var(--color-warm-dim)]/10',
  }
  return (
    <motion.button
      whileTap={disabled ? undefined : { scale: 0.97 }}
      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg px-4 py-2 text-sm transition-colors disabled:cursor-not-allowed
        disabled:opacity-40 ${variants[variant]} ${className}`}
    >
      {children}
    </motion.button>
  )
}

export function LocalBadge({ model, native }: { model: string | null; native?: boolean }) {
  return (
    <div className="flex items-center gap-3 text-[11px] text-[var(--color-faint)]">
      <span className="flex items-center gap-1.5">
        <span className="size-1.5 rounded-full bg-emerald-500" />
        no cloud connection
      </span>
      {model && <span className="font-mono text-[var(--color-muted)]">{model}</span>}
      {native && <span className="font-mono">native</span>}
    </div>
  )
}
