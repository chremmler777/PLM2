/**
 * Add from SEP: SEP items never enter the LOP by themselves. The PM picks
 * one item, or all open items of one gate. Each added line gets the
 * department's team member (else the PM) and the gate target date as
 * defaults, marked "default" in the list until the PM confirms them.
 */
import { useQuery } from '@tanstack/react-query'
import { lopApi, lopKeys } from '../../api/lop'
import { shortDay } from '../../lib/lop'
import type { SepCandidateGate } from '../../types/lop'
import Dialog from '../common/Dialog'
import { btnSm } from '../common/buttonStyles'
import { InlineError } from './lopUi'
import { useLopWrite } from './useLopWrite'

function GateBlock({ gate, projectId }: { gate: SepCandidateGate; projectId: number }) {
  const addItem = useLopWrite(projectId, (itemId: number) => lopApi.addSepItem(projectId, itemId),
    { fallback: 'The item could not be added.' })
  const addGate = useLopWrite(projectId, () => lopApi.addSepGate(projectId, gate.gate_id),
    { fallback: 'The gate could not be added.' })
  return (
    <section className="rounded-md border border-slate-700" aria-label={`Gate ${gate.code}`}>
      <header className="flex flex-wrap items-center gap-2 border-b border-slate-700 bg-slate-800/60 px-2.5 py-1.5">
        <h4 className="text-xs font-semibold text-slate-100">SEP {gate.code}</h4>
        <span className="text-[11px] text-slate-400">
          {gate.status.replace(/_/g, ' ')} · {gate.target_date ? `target ${shortDay(gate.target_date)}` : 'no target date'}
        </span>
        <button type="button" className={`${btnSm.secondary} ml-auto`} disabled={addGate.pending}
          onClick={() => addGate.run(undefined)}>
          Add all open items of this gate ({gate.items.length})
        </button>
      </header>
      <InlineError>{addGate.error}</InlineError>
      <ul className="divide-y divide-slate-700/60">
        {gate.items.map((item) => (
          <li key={item.id} className="flex items-center gap-2 px-2.5 py-1 text-xs">
            <span className="w-14 shrink-0 tabular-nums text-slate-500">item {item.item_no}</span>
            <span className="min-w-0 flex-1 text-slate-100">{item.title}</span>
            <span className="shrink-0 text-slate-400">{item.department ?? ''}</span>
            <button type="button" className={btnSm.ghost} disabled={addItem.pending} onClick={() => addItem.run(item.id)}>Add</button>
          </li>
        ))}
      </ul>
      <InlineError>{addItem.error}</InlineError>
    </section>
  )
}

export default function AddFromSepDialog({ projectId, open, onClose }: { projectId: number; open: boolean; onClose(): void }) {
  const candidates = useQuery({
    queryKey: lopKeys.sep(projectId),
    queryFn: () => lopApi.sepCandidates(projectId),
    enabled: open,
  })
  const gates = Array.isArray(candidates.data) ? candidates.data : []
  return (
    <Dialog open={open} onClose={onClose} size="lg" title="Add from SEP"
      description="Only what you add here enters the list. Each item gets its department’s team member (else you) and the gate target date as defaults.">
      <div className="flex max-h-[60vh] flex-col gap-2 overflow-y-auto">
        {candidates.isLoading && <p className="text-xs text-slate-400">Loading SEP items…</p>}
        {candidates.isError && <InlineError>The SEP items could not be loaded.</InlineError>}
        {candidates.isSuccess && gates.length === 0 && (
          <p className="text-xs text-slate-400">Every open SEP item of the open gates is already on the list.</p>
        )}
        {gates.map((g) => <GateBlock key={g.gate_id} gate={g} projectId={projectId} />)}
      </div>
    </Dialog>
  )
}
