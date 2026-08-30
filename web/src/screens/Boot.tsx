import { motion } from 'motion/react'
import { useEffect, useState } from 'react'
import { api, type Probe } from '../api'
import { Button, Panel, riseIn } from '../ui'

export function Boot({ onReady }: { onReady: (probe: Probe) => void }) {
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
        <h1 className="text-3xl font-medium tracking-tight">Ollie</h1>
        <p className="mt-3 max-w-md text-[15px] leading-relaxed text-[var(--color-muted)]">
          A dating simulator that runs on this machine. The conversation, the memory and the model
          all stay here. Nothing is uploaded, and there is no account.
        </p>
      </motion.div>

      <motion.div {...riseIn} transition={{ ...riseIn.transition, delay: 0.08 }} className="mt-8">
        <Panel title="this machine">
          {error && <p className="text-sm text-[var(--color-warm)]">{error}</p>}
          {!probe && !error && (
            <p className="text-sm text-[var(--color-faint)]">looking at your hardware…</p>
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
                    Ollama isn&rsquo;t running. Start it, then reload — Ollie won&rsquo;t install
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
        className="mt-6 flex items-center gap-4"
      >
        <Button onClick={() => probe && onReady(probe)} disabled={!probe?.model}>
          start
        </Button>
        <p className="text-[12px] text-[var(--color-faint)]">
          takes about three minutes. you can stop at any point.
        </p>
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
