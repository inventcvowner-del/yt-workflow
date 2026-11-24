import { useState } from 'react'
import * as api from './api'
import type { Command, FileItem, Job, Kind, StepName, Topic } from './api'
import { Button, Spinner } from './components/Button'
import { ConfirmDialog, type Question } from './components/ConfirmDialog'
import { LogPanel } from './components/LogPanel'
import { TopicRow } from './components/TopicRow'
import { label, pendingCount, STEPS } from './steps'
import { useWorkflow } from './useWorkflow'

const KINDS: { kind: Kind; label: string }[] = [
  { kind: 'short', label: 'Short videos' },
  { kind: 'long', label: 'Long videos' },
]
const FILTERS = [
  { name: 'all', label: 'All' },
  { name: 'todo', label: 'To do' },
  { name: 'uploaded', label: 'On YouTube' },
] as const
type Filter = (typeof FILTERS)[number]['name']

function outcome(job: Job): string {
  if (job.exitCode === 0) return 'finished'
  if (job.exitCode === 130) return 'stopped'
  return 'ended with something left to do or a problem (see the log)'
}

function Status({ job, busyElsewhere, onStop }: { job: Job; busyElsewhere: boolean; onStop: () => void }) {
  if (job.running) {
    return (
      <div className="flex items-center gap-3 text-sm">
        <span className="inline-flex items-center gap-2 text-sky-300">
          <Spinner /> Running: <span className="font-mono">{job.label}</span>
        </span>
        <Button variant="danger" onClick={onStop}>
          Stop
        </Button>
      </div>
    )
  }
  if (busyElsewhere) {
    return (
      <div className="text-sm text-amber-300">
        A command is running in another window. The buttons work again when it has finished.
      </div>
    )
  }
  return (
    <div className="text-sm text-slate-400">
      Idle
      {job.finished && (
        <>
          {' · last: '}
          <span className="font-mono">{job.label}</span> {outcome(job)}
        </>
      )}
    </div>
  )
}

export default function App() {
  const { workflow, lines, problem, offline, refresh, clearLog } = useWorkflow()
  const [kind, setKind] = useState<Kind>('short')
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')
  const [opened, setOpened] = useState<ReadonlySet<string>>(new Set())
  const [question, setQuestion] = useState<Question | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  if (!workflow) {
    return (
      <div className="flex h-screen items-center justify-center p-8 text-center text-slate-400">
        {offline ? (
          <p>
            The page's server is not running. In <span className="font-mono">yt-workflow</span> type{' '}
            <span className="font-mono text-slate-200">run ui</span> and leave that window open.
          </p>
        ) : (
          <p>{problem ?? 'Loading…'}</p>
        )}
      </div>
    )
  }

  const { job, busyElsewhere } = workflow
  const paused = offline
    ? 'The server is not running'
    : job.running
      ? `${job.label} is running`
      : busyElsewhere
        ? 'A command is running in another window'
        : null

  const act = async (work: () => Promise<unknown>) => {
    setFailure(null)
    try {
      await work()
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error))
    }
    await refresh()
  }

  const ofKind = workflow.topics.filter((topic) => topic.kind === kind)
  const pending = (name: StepName) => ofKind.reduce((sum, topic) => sum + pendingCount(topic.steps[name]), 0)
  const words = search.trim().toLowerCase()
  const shown = ofKind.filter(
    (topic) =>
      (filter === 'all' || (filter === 'uploaded') === topic.uploaded) &&
      (!words || `${topic.id} ${topic.name}`.toLowerCase().includes(words)),
  )
  const kindLabel = kind === 'short' ? 'short videos' : 'long videos'
  const uploadNote =
    'A video is uploaded with its title, description, tags and thumbnail and scheduled into the next free slot of the release plan. It becomes public at that time.'

  const generate = (topic: Topic, name: StepName) => {
    const start = () => act(() => api.runFor(name, topic))
    if (name !== 'upload') return void start()
    setQuestion({ title: `Upload "${topic.title}" to YouTube?`, lines: [uploadNote], action: 'Upload', run: start })
  }

  const regenerate = (topic: Topic, name: StepName, item?: FileItem) => {
    const step = topic.steps[name]
    const final = topic.steps.edit.file
    const texts: Record<StepName, string[]> = {
      audio: [`The ${step.done} voice file(s) of this video are moved to the Recycle Bin and generated again.`],
      clips: [`The ${step.done} clip(s) of this video are moved to the Recycle Bin and generated again.`],
      edit: [
        `${final ?? 'The unfinished edit'} and its Premiere project are moved to the Recycle Bin, and the video is edited and exported again. Premiere must be closed.`,
      ],
      thumbnails: [`${step.file} is moved to the Recycle Bin and a new thumbnail is asked for in ChatGPT.`],
      upload: [],
    }
    const notes = texts[name]
    if (item) notes[0] = `${item.name} is moved to the Recycle Bin and generated again.`
    if (name === 'audio') notes.push('This uses ElevenLabs credits.')
    if ((name === 'audio' || name === 'clips') && final) {
      notes.push(`${final} is not changed by this. Regenerate the edit afterwards to use the new file.`)
    }
    setQuestion({
      title: item ? `Regenerate ${item.name} of "${topic.title}"?` : `Regenerate the ${label(name).toLowerCase()} of "${topic.title}"?`,
      lines: notes,
      action: 'Regenerate',
      danger: true,
      run: () => act(() => api.regenerate(topic, name, item?.number)),
    })
  }

  const runAllFor = (topic: Topic) =>
    setQuestion({
      title: `Run all steps for "${topic.title}"?`,
      lines: ['Every step that is still missing is run in order: audio, clips, edit, thumbnail, upload.', uploadNote],
      action: 'Run all',
      run: () => act(() => api.runFor('all', topic)),
    })

  const runForKind = (command: Command) => {
    const start = () => act(() => api.run(command, { kind }))
    if (command !== 'upload' && command !== 'all') return void start()
    const counts = STEPS.map(({ name, label }) => `${label}: ${pending(name)}`).join(' · ')
    setQuestion({
      title: command === 'all' ? `Run everything that is pending for the ${kindLabel}?` : `Upload all finished ${kindLabel}?`,
      lines: command === 'all' ? [`To do now: ${counts}.`, uploadNote] : [`${pending('upload')} video(s) are ready.`, uploadNote],
      action: command === 'all' ? 'Run all' : 'Upload',
      run: start,
    })
  }

  const toggle = (key: string) => {
    const next = new Set(opened)
    if (!next.delete(key)) next.add(key)
    setOpened(next)
  }

  return (
    <div className="min-h-screen pb-64">
      <header className="sticky top-0 z-10 border-b border-slate-800 bg-slate-950/95 px-4 py-3 backdrop-blur">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
          <h1 className="text-base font-semibold text-slate-100">YouTube workflow</h1>
          <Status job={job} busyElsewhere={busyElsewhere} onStop={() => act(api.stop)} />
        </div>
        {(failure || problem || offline) && (
          <div className="mt-2 flex items-start gap-3 rounded border border-rose-500/40 bg-rose-950/40 px-3 py-2 text-sm text-rose-200">
            <span className="flex-1">
              {failure ?? problem ?? 'The server is not answering. Is the "run ui" window still open?'}
            </span>
            {failure && (
              <button type="button" className="text-rose-300 hover:text-white" onClick={() => setFailure(null)}>
                Dismiss
              </button>
            )}
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <div className="flex rounded border border-slate-700 text-sm">
            {KINDS.map((tab) => (
              <button
                key={tab.kind}
                type="button"
                className={`px-3 py-1 ${kind === tab.kind ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                onClick={() => setKind(tab.kind)}
              >
                {tab.label} ({workflow.topics.filter((topic) => topic.kind === tab.kind).length})
              </button>
            ))}
          </div>
          <div className="flex gap-1 text-sm">
            {FILTERS.map((option) => (
              <button
                key={option.name}
                type="button"
                className={`rounded px-2 py-1 ${filter === option.name ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-slate-200'}`}
                onClick={() => setFilter(option.name)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <input
            type="search"
            value={search}
            placeholder="Find a video"
            aria-label="Find a video"
            className="w-48 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
            onChange={(event) => setSearch(event.target.value)}
          />
          <Button
            variant="primary"
            className="ml-auto px-3 py-1.5"
            disabled={!!paused || STEPS.every(({ name }) => pending(name) === 0)}
            title={paused ?? undefined}
            onClick={() => runForKind('all')}
          >
            Run all pending {kindLabel}
          </Button>
        </div>
      </header>

      <table className="w-full table-fixed border-collapse">
        <thead>
          <tr className="text-left text-xs text-slate-400">
            <th className="w-[24%] px-3 py-2 font-medium">Video</th>
            {STEPS.map(({ name, label }) => (
              <th key={name} className="px-3 py-2 font-medium">
                <div className="flex items-center gap-2">
                  <span className="text-slate-200">{label}</span>
                  {pending(name) > 0 && (
                    <>
                      <span>{pending(name)} to do</span>
                      <Button disabled={!!paused} title={paused ?? `run ${name} for all ${kindLabel}`} onClick={() => runForKind(name)}>
                        Run all
                      </Button>
                    </>
                  )}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((topic) => {
            const key = `${topic.kind}/${topic.name}`
            return (
              <TopicRow
                key={key}
                topic={topic}
                job={job}
                paused={paused}
                open={opened.has(key)}
                onToggle={() => toggle(key)}
                onGenerate={(name) => generate(topic, name)}
                onRegenerate={(name, item) => regenerate(topic, name, item)}
                onRunAll={() => runAllFor(topic)}
                onOpen={(what) => act(() => api.open(topic, what))}
              />
            )
          })}
        </tbody>
      </table>
      {shown.length === 0 && <p className="p-8 text-center text-sm text-slate-500">No videos match.</p>}

      <LogPanel lines={lines} onClear={clearLog} />
      <ConfirmDialog question={question} onClose={() => setQuestion(null)} />
    </div>
  )
}
