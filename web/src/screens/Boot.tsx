import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { api, type Candidate, type Probe } from '../api'
import { Button, Panel, Waiting, riseIn } from '../ui'

export function Boot({
  onReady,
  onResume,
}: {
  onReady: (probe: Probe) => void
  onResume: (probe: Probe, persona: Candidate) => void
}) {
  const [probe, setProbe] = useState<Probe | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .probe()
      .then(setProbe)
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center px-6 py-16">
      <motion.div {...riseIn}>
        {/* Scale contrast carries the hierarchy here: the name is roughly 7x the body,
            which is what makes the screen read as an opening rather than a form. */}
        <h1
          className="font-display font-medium leading-[0.85]"
          style={{ fontSize: 'clamp(3.5rem, 11vw, 7rem)', letterSpacing: '-0.035em' }}
        >
          Ollie
        </h1>
        <p className="mt-6 max-w-[46ch] text-[15px] leading-relaxed text-[var(--color-muted)]">
          A dating simulator that runs on this machine. It interviews you, works out your type,
          and becomes someone who will disagree with you about things.
        </p>
        <p className="mt-2 max-w-[46ch] text-[13px] leading-relaxed text-[var(--color-faint)]">
          The conversation, the memory and the model all stay here. Nothing is uploaded and there
          is no account.
        </p>
      </motion.div>

      <motion.div {...riseIn} transition={{ ...riseIn.transition, delay: 0.08 }} className="mt-8">
        <Panel title="this machine">
          {error && <p className="text-sm text-[var(--color-warm)]">{error}</p>}
          {!probe && !error && (
            <Waiting label="looking at your hardware" />
          )}
          {probe && (
            <div className="space-y-3">
              <p className="font-mono text-[13px] text-[var(--color-text)]">{probe.summary}</p>

              <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-[13px]">
                <Row label="memory" value={`${probe.hardware.ram_gb} GB`} />
                <Row label="free now" value={`${probe.hardware.ram_available_gb} GB`} />
                <Row label="cores" value={String(probe.hardware.cores_physical)} />
                <Row label="disk free" value={`${probe.hardware.disk_free_gb} GB`} />
              </div>

              <div className="border-t border-[var(--color-line)] pt-3 text-[13px]">
                {!probe.ollama ? (
                  <p className="text-[var(--color-warm)]">
                    Ollama isn&rsquo;t running. Start it, then reload. Ollie won&rsquo;t install
                    anything for you without asking.
                  </p>
                ) : probe.model ? (
                  <Row label="model" value={probe.model} mono />
                ) : (
                  <p className="text-[var(--color-warm)]">
                    No suitable model installed. Closest fit for this machine:{' '}
                    <code className="font-mono">{probe.suggested_pull}</code>
                  </p>
                )}
              </div>
            </div>
          )}
        </Panel>
      </motion.div>

      <motion.div
        {...riseIn}
        transition={{ ...riseIn.transition, delay: 0.16 }}
        className="mt-6 flex flex-wrap items-center gap-4"
      >
        {/* Resuming leads when there is something to resume. Someone who already has a
            conversation open almost never wants to start a second one, and making them
            walk back through onboarding to reach it would be the opposite of a product
            that claims to remember them. */}
        {probe?.resumable ? (
          <>
            <Button
              onClick={() => probe && onResume(probe, probe.resumable!.persona)}
              disabled={!probe.model}
            >
              back to {probe.resumable.persona.display_name}
            </Button>
            <Button variant="ghost" onClick={() => probe && onReady(probe)}
                    disabled={!probe.model}>
              start over
            </Button>
            <p className="text-[12px] text-[var(--color-faint)]">
              episode {probe.resumable.episode}, {probe.resumable.messages}{' '}
              {probe.resumable.messages === 1 ? 'message' : 'messages'} in
            </p>
          </>
        ) : (
          <>
            <Button onClick={() => probe && onReady(probe)} disabled={!probe?.model}>
              start
            </Button>
            <p className="text-[12px] text-[var(--color-faint)]">
              takes about three minutes. you can stop at any point.
            </p>
          </>
        )}
      </motion.div>
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-[var(--color-faint)]">{label}</span>
      <span className={mono ? 'font-mono text-[var(--color-muted)]' : 'text-[var(--color-muted)]'}>
        {value}
      </span>
    </div>
  )
}
