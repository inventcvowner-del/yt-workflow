import type { FileItem, Job, Step, StepName, Topic } from '../api'
import { isWorking, label, STEPS } from '../steps'
import { Button } from './Button'
import { StepCell } from './StepCell'

interface Props {
  topic: Topic
  job: Job
  /** Why nothing can be started at the moment, if so. */
  paused: string | null
  open: boolean
  onToggle: () => void
  onGenerate: (name: StepName) => void
  onRegenerate: (name: StepName, item?: FileItem) => void
  onRunAll: () => void
  onOpen: (what: 'folder' | 'video') => void
}

/** The voices or clips of a video, each with its own Regenerate. */
function Files({ title, step, paused, onRegenerate }: {
  title: string
  step: Step
  paused: string | null
  onRegenerate: (item: FileItem) => void
}) {
  if (!step.items?.length) return null
  return (
    <div>
      <div className="mb-1 text-xs font-medium tracking-wide text-slate-500 uppercase">{title}</div>
      <div className="flex flex-wrap gap-1.5">
        {step.items.map((item) => (
          <span
            key={item.number}
            className={`inline-flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs ${
              item.exists ? 'border-slate-700 text-slate-300' : 'border-amber-500/40 text-amber-300'
            }`}
          >
            {item.name}
            {!item.exists && <em className="text-amber-400/80">missing</em>}
            {item.exists && step.regenerate && (
              <button
                type="button"
                className="text-slate-500 hover:text-sky-300 disabled:cursor-not-allowed disabled:hover:text-slate-500"
                disabled={!!paused}
                title={paused ?? `Regenerate ${item.name}`}
                aria-label={`Regenerate ${item.name}`}
                onClick={() => onRegenerate(item)}
              >
                ↻
              </button>
            )}
          </span>
        ))}
      </div>
    </div>
  )
}

export function TopicRow({ topic, job, paused, open, onToggle, onGenerate, onRegenerate, onRunAll, onOpen }: Props) {
  const { steps } = topic
  const notes = STEPS.filter(
    ({ name }) => steps[name].reasons.length > 0 && !(topic.uploaded && steps[name].state === 'blocked'),
  )
  const somethingToDo = STEPS.some(({ name }) => steps[name].state === 'pending')

  return (
    <>
      <tr className={`border-t border-slate-800 ${open ? 'bg-slate-900/70' : 'hover:bg-slate-900/40'}`}>
        <td className="px-3 py-2 align-top">
          <button type="button" className="flex w-full items-start gap-2 text-left" aria-expanded={open} onClick={onToggle}>
            <span className="mt-0.5 w-3 shrink-0 text-xs text-slate-500">{open ? '▾' : '▸'}</span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-slate-100">{topic.title}</span>
              <span className="text-xs text-slate-500">
                {topic.id ?? topic.name}
                {topic.uploaded && ' · on YouTube'}
              </span>
            </span>
          </button>
        </td>
        {STEPS.map(({ name }) => (
          <StepCell
            key={name}
            name={name}
            step={steps[name]}
            uploaded={topic.uploaded}
            working={isWorking(job, topic, name)}
            paused={paused}
            onGenerate={() => onGenerate(name)}
            onRegenerate={() => onRegenerate(name)}
          />
        ))}
      </tr>
      {open && (
        <tr className="bg-slate-900/70">
          <td colSpan={STEPS.length + 1} className="space-y-3 px-3 pt-1 pb-4 pl-8">
            <Files title="Voices" step={steps.audio} paused={paused} onRegenerate={(item) => onRegenerate('audio', item)} />
            <Files title="Clips" step={steps.clips} paused={paused} onRegenerate={(item) => onRegenerate('clips', item)} />
            {notes.length > 0 && (
              <ul className="space-y-0.5 text-xs text-slate-400">
                {notes.map(({ name }) => (
                  <li key={name}>
                    <span className="text-slate-300">{label(name)}:</span> {steps[name].reasons.join('; ')}
                  </li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={() => onOpen('folder')}>Open folder</Button>
              {steps.edit.file && <Button onClick={() => onOpen('video')}>Play {steps.edit.file}</Button>}
              {steps.upload.url && (
                <a
                  className="rounded border border-slate-700 px-2.5 py-1 text-xs font-medium text-slate-300 hover:bg-slate-800"
                  href={steps.upload.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open on YouTube
                </a>
              )}
              {somethingToDo && (
                <Button variant="primary" disabled={!!paused} title={paused ?? undefined} onClick={onRunAll}>
                  Run all steps for this video
                </Button>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  )
}
