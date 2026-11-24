import type { Job, Step, StepName, Topic } from './api'

export const STEPS: { name: StepName; label: string; files: string }[] = [
  { name: 'audio', label: 'Audio', files: 'voices' },
  { name: 'clips', label: 'Clips', files: 'clips' },
  { name: 'edit', label: 'Edit', files: 'final video' },
  { name: 'thumbnails', label: 'Thumbnail', files: 'thumbnail' },
  { name: 'upload', label: 'Upload', files: 'upload' },
]

export const label = (name: StepName) => STEPS.find((step) => step.name === name)!.label

/** How many files (voices, clips) or videos a step still has to make. */
export function pendingCount(step: Step): number {
  if (step.state !== 'pending') return 0
  return step.total ? step.total - (step.done ?? 0) : 1
}

/** The one line a cell shows for a step. */
export function describe(step: Step): string {
  if (step.total) return `${step.done} / ${step.total}`
  if (step.state === 'done') return step.detail ?? step.file ?? 'Done'
  if (step.state === 'pending') return 'Ready'
  return step.reasons[0] ?? 'Not ready'
}

/** Whether the running command is working on this step of this topic. */
export function isWorking(job: Job, topic: Topic, name: StepName): boolean {
  if (!job.running || (job.kind && job.kind !== topic.kind) || (job.topic && job.topic !== topic.name)) return false
  if (job.command !== name && job.command !== 'all') return false
  const step = topic.steps[name]
  // An edit that is being exported has its Premiere project but no final video yet.
  return step.state === 'pending' || (name === 'edit' && step.state === 'blocked' && !!step.regenerate)
}
