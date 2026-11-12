/**
 * Flag a tool that has no sampling date: the Project Manager says in which
 * week the sampling is wanted and why. PDB gets an open sampling request, so
 * the tool stands on Scheduling's list as waiting for a slot. The slot itself
 * is booked in PDB.
 */
import { useState } from 'react'
import { lopApi } from '../../api/lop'
import type { PdbTool, SamplingPurpose, SamplingRequestBody } from '../../types/lop'
import Dialog from '../common/Dialog'
import Button from '../common/Button'
import { InlineError, inputCls, labelCls } from './lopUi'
import { useLopWrite } from './useLopWrite'

const PURPOSES: { value: SamplingPurpose; label: string }[] = [
  { value: 'validation_mrr', label: 'Validation / MRR' },
  { value: 'material_test', label: 'Material test' },
  { value: 'ecr_validation', label: 'ECR validation' },
  { value: 'part_demand', label: 'Part demand' },
]

/** Monday of next week, as yyyy-mm-dd (local time). */
export function nextMonday(from = new Date()): string {
  const d = new Date(from.getFullYear(), from.getMonth(), from.getDate())
  d.setDate(d.getDate() + ((8 - d.getDay()) % 7 || 7))
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export default function RequestSamplingDialog({ projectId, tool, onClose }: {
  projectId: number; tool: PdbTool; onClose(): void
}) {
  const [week, setWeek] = useState(() => nextMonday())
  const [purpose, setPurpose] = useState<SamplingPurpose>('validation_mrr')
  const [note, setNote] = useState('')
  const send = useLopWrite(projectId,
    (body: SamplingRequestBody) => lopApi.requestSampling(projectId, tool.tool_number, body),
    { fallback: 'The request could not be sent to PDB.', onDone: () => onClose() })
  return (
    <Dialog open onClose={onClose} busy={send.pending} closeOnBackdrop={false} data-testid="pdb-request-dialog"
      title="Sampling needs to be planned"
      description={`Tool ${tool.tool_number}${tool.tool_name ? ` · ${tool.tool_name}` : ''}. PDB Scheduling gets a request and places it on the schedule.`}
      footer={(
        <>
          <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button size="sm" variant="primary" disabled={!week} loading={send.pending} data-testid="pdb-request-send"
            onClick={() => send.run({ preferred_week: week, purpose, note: note.trim() || null })}>Send to PDB</Button>
        </>
      )}>
      <div className="flex flex-col gap-2">
        <div className="flex gap-2">
          <label className={labelCls}>Wanted in the week of
            <input type="date" className={inputCls} value={week} onChange={(e) => setWeek(e.target.value)} data-autofocus />
          </label>
          <label className={labelCls}>Why
            <select className={inputCls} value={purpose} onChange={(e) => setPurpose(e.target.value as SamplingPurpose)}>
              {PURPOSES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select>
          </label>
        </div>
        <label className={labelCls}>Note for Scheduling (optional)
          <textarea className={inputCls} rows={2} maxLength={1500} value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
        <p className="text-[11px] text-slate-400">Any day of the week is fine. The request stays open in PDB until a slot is booked.</p>
        <InlineError>{send.error}</InlineError>
      </div>
    </Dialog>
  )
}
