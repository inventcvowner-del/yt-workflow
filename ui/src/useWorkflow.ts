import { useCallback, useEffect, useRef, useState } from 'react'
import { getLog, getWorkflow, type Workflow } from './api'

const INTERVAL = 1500 // milliseconds between looks at the server
const KEPT_LINES = 5000

/** The state of every topic and the output of the running command, kept up to date. */
export function useWorkflow() {
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [lines, setLines] = useState<string[]>([])
  const [problem, setProblem] = useState<string | null>(null) // the server answered with an error
  const [offline, setOffline] = useState(false) // the server did not answer: "run ui" is not running
  const cursor = useRef(0) // the number of the next log line to ask for
  const asking = useRef(false)

  const refresh = useCallback(async () => {
    if (asking.current) return
    asking.current = true
    try {
      const [next, log] = await Promise.all([getWorkflow(), getLog(cursor.current)])
      setWorkflow(next)
      setProblem(null)
      setOffline(false)
      if (log.next < cursor.current) {
        cursor.current = 0 // the server was started again: its log begins anew
        setLines([])
      } else {
        cursor.current = log.next
        if (log.lines.length) setLines((old) => [...old, ...log.lines].slice(-KEPT_LINES))
      }
    } catch (error) {
      const unreachable = error instanceof TypeError // what fetch throws when it cannot connect
      setOffline(unreachable)
      setProblem(unreachable ? null : error instanceof Error ? error.message : String(error))
    } finally {
      asking.current = false
    }
  }, [])

  useEffect(() => {
    void refresh()
    const timer = setInterval(() => void refresh(), INTERVAL)
    return () => clearInterval(timer)
  }, [refresh])

  return { workflow, lines, problem, offline, refresh, clearLog: () => setLines([]) }
}
