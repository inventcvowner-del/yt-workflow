import { useEffect } from 'react'
import { Button } from './Button'

/** A question the page asks before it does something that cannot simply be undone. */
export interface Question {
  title: string
  lines: string[]
  action: string
  danger?: boolean
  run: () => void
}

export function ConfirmDialog({ question, onClose }: { question: Question | null; onClose: () => void }) {
  useEffect(() => {
    if (!question) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [question, onClose])

  if (!question) return null
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="question-title"
        className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-900 p-5 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="question-title" className="text-base font-semibold text-slate-100">
          {question.title}
        </h2>
        <div className="mt-3 space-y-2 text-sm text-slate-300">
          {question.lines.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button autoFocus onClick={onClose} className="px-3 py-1.5 text-sm">
            Cancel
          </Button>
          <Button
            variant={question.danger ? 'danger' : 'primary'}
            className="px-3 py-1.5 text-sm"
            onClick={() => {
              onClose()
              question.run()
            }}
          >
            {question.action}
          </Button>
        </div>
      </div>
    </div>
  )
}
