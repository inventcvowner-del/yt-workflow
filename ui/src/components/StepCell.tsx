import type { Step, StepName } from '../api'
import { describe } from '../steps'
import { Button, Spinner } from './Button'

const MARKS: Record<Step['state'], { symbol: string; tone: string }> = {
  done: { symbol: '✓', tone: 'text-emerald-400' },
  pending: { symbol: '●', tone: 'text-amber-400' },
  blocked: { symbol: '○', tone: 'text-slate-600' },
  attention: { symbol: '!', tone: 'text-rose-400' },
}

interface Props {
  name: StepName
  step: Step
  /** The video is already on YouTube: what it lacks is no longer needed. */
  uploaded: boolean
  /** The running command is working on this step now. */
  working: boolean
  /** Why nothing can be started at the moment, if so. */
  paused: string | null
  onGenerate: () => void
  onRegenerate: () => void
}

/** One step of one video: what exists, and the button for what can be done about it. */
export function StepCell({ name, step, uploaded, working, paused, onGenerate, onRegenerate }: Props) {
  const mark = MARKS[step.state]
  const why = step.reasons.join('; ')
  const verb = name === 'upload' ? 'Upload' : 'Generate'
  const notNeeded = uploaded && step.state === 'blocked'
  // While an edit is exported its project exists but its video does not: not worth explaining as a problem.
  const text = notNeeded ? 'Not needed' : working && step.state === 'blocked' ? 'In progress' : describe(step)

  let action = null
  if (working) {
    action = (
      <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap text-sky-300">
        <Spinner /> Working…
      </span>
    )
  } else if (step.state === 'pending') {
    action = (
      <Button variant="primary" disabled={!!paused} title={paused ?? undefined} onClick={onGenerate}>
        {verb}
      </Button>
    )
  } else if (step.regenerate) {
    action = (
      <Button disabled={!!paused} title={paused ?? undefined} onClick={onRegenerate}>
        Regenerate
      </Button>
    )
  } else if (step.state === 'blocked' && !notNeeded) {
    action = (
      <Button variant="primary" disabled title={why}>
        {verb}
      </Button>
    )
  }

  return (
    <td className="px-3 py-2 align-top">
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-1.5 text-sm" title={why || step.locked || undefined}>
          <span className={`w-4 shrink-0 text-center font-bold ${mark.tone}`}>{mark.symbol}</span>
          <span className={`truncate ${step.state === 'blocked' ? 'text-slate-500' : ''}`}>{text}</span>
        </div>
        {action}
      </div>
      {step.stale && <div className="pl-5.5 text-xs text-amber-400">older than its clips or voices</div>}
    </td>
  )
}
