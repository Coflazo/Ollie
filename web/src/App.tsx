import { AnimatePresence, motion } from 'motion/react'
import { useState } from 'react'
import type { Candidate, Probe, Read } from './api'
import { Boot } from './screens/Boot'
import { Candidates } from './screens/Candidates'
import { Chat } from './screens/Chat'
import { Onboarding, type Matching } from './screens/Onboarding'
import { ease } from './ui'

type Stage =
  | { name: 'boot' }
  | { name: 'onboarding' }
  | { name: 'candidates'; read: Read; matching: Matching; candidates: Candidate[] }
  | { name: 'chat'; persona: Candidate }

export default function App() {
  const [stage, setStage] = useState<Stage>({ name: 'boot' })
  const [probe, setProbe] = useState<Probe | null>(null)

  return (
    // Wrapping the whole app kills the horizontal scrollbar that off-screen exit
    // animations would otherwise introduce for one frame.
    <div className="h-full w-full max-w-full overflow-x-hidden">
      <AnimatePresence mode="wait">
        <motion.div
          key={stage.name}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2, ease }}
          className="h-full"
        >
          {stage.name === 'boot' && (
            <Boot
              onReady={(p) => {
                setProbe(p)
                setStage({ name: 'onboarding' })
              }}
            />
          )}

          {stage.name === 'onboarding' && (
            <Onboarding
              onDone={(d) =>
                setStage({
                  name: 'candidates',
                  read: d.read,
                  matching: d.matching,
                  candidates: d.candidates,
                })
              }
            />
          )}

          {stage.name === 'candidates' && (
            <Candidates
              read={stage.read}
              matching={stage.matching}
              candidates={stage.candidates}
              onChosen={(persona) => setStage({ name: 'chat', persona })}
            />
          )}

          {stage.name === 'chat' && (
            <Chat persona={stage.persona} model={probe?.model ?? null} />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
