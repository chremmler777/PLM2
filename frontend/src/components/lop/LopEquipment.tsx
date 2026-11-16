/**
 * Equipment on a LOP line: tools, gauges, EOATs and assembly equipment of the
 * project, picked from PLM (the one source for them). EquipmentPicker is the
 * chips + "add" select on + Task and in the editor; EquipmentTags shows the
 * links on a row. Picking a tool shows a hint: topics from a sampling belong
 * in PDB so they count for the tool's status; the LOP is for what PDB does
 * not track. A hint only, it never blocks.
 */
import { useQuery } from '@tanstack/react-query'
import { lopApi, lopKeys } from '../../api/lop'
import { pdbToolUrl } from '../../lib/lop'
import type { LopEquipment } from '../../types/lop'
import { inputCls, labelCls } from './lopUi'

export const KIND_LABEL: Record<LopEquipment['kind'], string> = {
  tool: 'Tool', gauge: 'Gauge', eoat: 'EOAT', assembly_equipment: 'Assembly equipment',
}
const KIND_GROUPS: { kind: LopEquipment['kind']; label: string }[] = [
  { kind: 'tool', label: 'Tools' }, { kind: 'gauge', label: 'Gauges' },
  { kind: 'eoat', label: 'EOATs' }, { kind: 'assembly_equipment', label: 'Assembly equipment' },
]
const KIND_TONE: Record<LopEquipment['kind'], string> = {
  tool: 'border-orange-800/70 text-orange-200', gauge: 'border-pink-800/70 text-pink-200',
  eoat: 'border-cyan-800/70 text-cyan-200', assembly_equipment: 'border-cyan-800/70 text-cyan-200',
}

export function EquipmentTags({ equipment }: { equipment: LopEquipment[] | undefined }) {
  if (!equipment?.length) return null
  return (
    <div data-testid="lop-row-equipment" className="mt-0.5 flex flex-wrap gap-1">
      {equipment.map((e) => (
        <span key={e.id} title={`${KIND_LABEL[e.kind]}: ${e.name}`}
          className={`rounded border px-1 text-[11px] tabular-nums ${KIND_TONE[e.kind]}`}>
          {KIND_LABEL[e.kind]} {e.part_number}
        </span>
      ))}
    </div>
  )
}

export function EquipmentPicker({ projectId, value, onChange, testId }: {
  projectId: number; value: number[]; onChange(ids: number[]): void; testId?: string
}) {
  const q = useQuery({ queryKey: lopKeys.equipment(projectId), queryFn: () => lopApi.equipment(projectId), staleTime: 60_000 })
  const all: LopEquipment[] = Array.isArray(q.data) ? q.data : []
  const byId = new Map(all.map((e) => [e.id, e]))
  const free = all.filter((e) => !value.includes(e.id))
  const tools = value.map((id) => byId.get(id)).filter((e): e is LopEquipment => e?.kind === 'tool')
  return (
    <div className={labelCls} data-testid={testId}>
      <span>Equipment</span>
      <div className="flex flex-wrap items-center gap-1.5">
        {value.map((id) => {
          const e = byId.get(id)
          const text = e ? `${KIND_LABEL[e.kind]} ${e.part_number}` : `item ${id}`
          return (
            <span key={id} title={e?.name} className="flex h-7 items-center gap-1 rounded-md border border-slate-600 px-2 text-xs text-slate-100">
              {text}
              <button type="button" aria-label={`Remove ${text}`} className="text-slate-500 hover:text-red-300"
                onClick={() => onChange(value.filter((x) => x !== id))}>✕</button>
            </span>
          )
        })}
        {free.length > 0 && (
          <select className={inputCls} value="" aria-label="Link equipment"
            onChange={(e) => { if (e.target.value) onChange([...value, Number(e.target.value)]) }}>
            <option value="">{value.length ? 'link another…' : 'none · link…'}</option>
            {KIND_GROUPS.map((g) => {
              const items = free.filter((e) => e.kind === g.kind)
              return items.length === 0 ? null : (
                <optgroup key={g.kind} label={g.label}>
                  {items.map((e) => <option key={e.id} value={e.id}>{e.part_number} · {e.name}</option>)}
                </optgroup>
              )
            })}
          </select>
        )}
        {q.isSuccess && all.length === 0 && (
          <span className="text-[11px] text-slate-500">No tools, gauges or equipment in PLM for this project yet.</span>
        )}
        {q.isError && <span className="text-[11px] text-amber-300">The equipment list could not be loaded.</span>}
      </div>
      {tools.length > 0 && (
        <p data-testid="lop-tool-hint" className="mt-1 max-w-[46rem] text-[11px] text-amber-200">
          Tool topics from a sampling (part quality, process, tool corrections) belong in PDB, so they count for the
          tool status. Use the LOP for what PDB does not track.{' '}
          {tools.map((t) => (
            <a key={t.id} href={pdbToolUrl(t.part_number)} target="_blank" rel="noreferrer"
              className="mr-2 underline decoration-dotted underline-offset-2 hover:text-amber-100">Open {t.part_number} in PDB ↗</a>
          ))}
        </p>
      )}
    </div>
  )
}
