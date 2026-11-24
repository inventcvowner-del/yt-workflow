// What scripts\server.py serves. A button on the page starts the same command as the command line.

export type Kind = 'short' | 'long'
export type StepName = 'audio' | 'clips' | 'edit' | 'thumbnails' | 'upload'
export type Command = StepName | 'all'

export interface FileItem {
  number: number
  name: string
  exists: boolean
}

export interface Step {
  /** done: everything exists. pending: it can be made now. blocked: see reasons. attention: needs you. */
  state: 'done' | 'pending' | 'blocked' | 'attention'
  reasons: string[]
  /** Whether "Regenerate" is offered, and if not for something that exists, why. */
  regenerate?: boolean
  locked?: string | null
  /** Audio and clips: one file per voice or clip. */
  items?: FileItem[]
  done?: number
  total?: number
  file?: string
  /** Edit: the final video is older than a clip or voice. */
  stale?: boolean
  detail?: string
  url?: string | null
}

export interface Topic {
  kind: Kind
  name: string
  title: string
  /** How the command line names the video, e.g. short-11. */
  id: string | null
  uploaded: boolean
  steps: Record<StepName, Step>
}

export interface Job {
  command: Command | null
  kind: Kind | null
  topic: string | null
  label: string
  started: number | null
  finished: number | null
  exitCode: number | null
  running: boolean
}

export interface Workflow {
  job: Job
  /** run.py is working in another window: nothing can be started from the page. */
  busyElsewhere: boolean
  topics: Topic[]
}

export interface Log {
  next: number
  lines: string[]
}

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(
    path,
    body && { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) },
  )
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.error ?? `The server answered ${response.status}`)
  return data as T
}

const target = (topic: Topic) => ({ kind: topic.kind, topic: topic.name })

export const getWorkflow = () => request<Workflow>('/api/state')
export const getLog = (since: number) => request<Log>(`/api/log?since=${since}`)
export const run = (command: Command, on: { kind?: Kind; topic?: string }) => request('/api/run', { command, ...on })
export const runFor = (command: Command, topic: Topic) => run(command, target(topic))
export const regenerate = (topic: Topic, step: StepName, number?: number) =>
  request('/api/regenerate', { ...target(topic), step, number })
export const stop = () => request('/api/stop', {})
export const open = (topic: Topic, what: 'folder' | 'video') => request('/api/open', { ...target(topic), what })
