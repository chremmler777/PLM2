/**
 * Visual harness for the generic Gantt (not routed in the app). A Playwright
 * script builds it with a throwaway vite entry and screenshots it: 300 tasks
 * with summaries, all link types, baselines, ideas, markers and holidays.
 * The query string picks the scenario: ?n=300&theme=dark&zoom=week&cal=working
 */
import { useMemo, useRef, useState } from 'react'
import { Gantt, type GanttHandle } from '../Gantt'
import { applyChangeSet } from '../engine/changes'
import type { ApplyResult, ChangeSet } from '../engine/types'
import type { GanttThemeName } from '../theme'
import { DEMO_KINDS, demoModel } from './demoData'
import type { Zoom } from '../layout'

export default function GanttDemo() {
  const q = new URLSearchParams(typeof location !== 'undefined' ? location.search : '')
  const n = Number(q.get('n') ?? 300)
  const theme = (q.get('theme') ?? 'dark') as GanttThemeName
  const zoom = (q.get('zoom') ?? 'week') as Zoom | 'fit'
  const working = q.get('cal') === 'working'
  const [model, setModel] = useState(() => demoModel(n))
  const [log, setLog] = useState<string[]>([])
  const ref = useRef<GanttHandle>(null)
  const calendar = useMemo(() => ({
    mode: working ? 'working' as const : 'calendar' as const, workdays: [1, 2, 3, 4, 5], holidays: ['2026-10-26', '2026-12-24', '2026-12-25'],
  }), [working])
  let seq = 1000
  const onChange = async (cs: ChangeSet): Promise<ApplyResult> => {
    await new Promise((r) => setTimeout(r, 120))
    const idMap: Record<string, number> = {}
    for (const t of cs.addTasks ?? []) if (typeof t.id === 'string') idMap[t.id] = ++seq
    setModel((m) => {
      const next = applyChangeSet(m, cs)
      const remap = (x: string | number) => idMap[String(x)] ?? x
      return {
        tasks: next.tasks.map((t) => ({ ...t, id: remap(t.id), parentId: t.parentId != null ? remap(t.parentId) : t.parentId })),
        links: next.links.map((l) => ({ ...l, from: remap(l.from), to: remap(l.to) })),
      }
    })
    setLog((l) => [`${cs.label ?? 'change'}`, ...l].slice(0, 5))
    return { idMap }
  }
  return (
    <div style={{ padding: 16, background: theme === 'dark' ? '#020617' : '#f1f5f9', minHeight: '100vh' }} data-testid="demo">
      <Gantt ref={ref} tasks={model.tasks} links={model.links} calendar={calendar} kinds={DEMO_KINDS}
        onChange={onChange} onError={(m) => setLog((l) => [`ERROR ${m}`, ...l])} theme={theme} defaultZoom={zoom}
        columns={['row', 'wbs', 'name', 'start', 'end', 'duration', 'predecessors', 'progress', 'slack']}
        markers={[{ id: 'release', date: '2027-02-15', label: 'Release', color: '#ef4444' }, { id: 'quote', date: '2026-11-02', label: 'Quote deadline', color: '#f59e0b' }]}
        showBaselines showProgress criticalPath height="calc(100vh - 110px)" exportName="demo-plan" />
      <p data-testid="demo-log" style={{ color: '#94a3b8', fontSize: 11, marginTop: 6 }}>{log.join(' | ')}</p>
    </div>
  )
}
