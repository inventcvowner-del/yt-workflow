import { useEffect, useRef, useState } from 'react'
import { Button } from './Button'

function tone(line: string): string {
  if (line.startsWith('>')) return 'text-sky-300'
  if (/ ERROR | CRITICAL |Traceback|Error:/.test(line)) return 'text-rose-400'
  if (/ WARNING /.test(line)) return 'text-amber-300'
  return 'text-slate-300'
}

/** What the commands print, the same lines as in logs\automation.log. */
export function LogPanel({ lines, onClear }: { lines: string[]; onClear: () => void }) {
  const [open, setOpen] = useState(true)
  const box = useRef<HTMLDivElement>(null)
  const following = useRef(true) // stays at the newest line until you scroll up

  useEffect(() => {
    if (box.current && following.current) box.current.scrollTop = box.current.scrollHeight
  }, [lines, open])

  return (
    <section className="fixed inset-x-0 bottom-0 z-20 border-t border-slate-800 bg-slate-900">
      <div className="flex items-center gap-3 px-4 py-1.5">
        <button type="button" className="text-sm font-medium text-slate-200" onClick={() => setOpen(!open)}>
          {open ? '▾' : '▸'} Log
        </button>
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-slate-500">
          {!open && lines[lines.length - 1]}
        </span>
        {open && lines.length > 0 && <Button onClick={onClear}>Clear</Button>}
      </div>
      {open && (
        <div
          ref={box}
          className="h-44 overflow-y-auto px-4 pb-2 font-mono text-xs leading-5"
          onScroll={(event) => {
            const view = event.currentTarget
            following.current = view.scrollHeight - view.scrollTop - view.clientHeight < 24
          }}
        >
          {lines.length === 0 && <div className="text-slate-600">Nothing has been run from this page yet.</div>}
          {lines.map((line, index) => (
            <div key={index} className={`break-words whitespace-pre-wrap ${tone(line)}`}>
              {line}
            </div>
          ))}
        </div>
      )}
    </section>
  )
}
