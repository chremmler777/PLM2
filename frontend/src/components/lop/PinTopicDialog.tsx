/**
 * Pin a PDB topic: the PM gives it a responsible person and a due date or
 * a next-check date. The topic stays a PDB topic (closed in PDB only).
 */
import { useState } from 'react'
import { lopApi } from '../../api/lop'
import type { LopLine, PinBody } from '../../types/lop'
import Dialog from '../common/Dialog'
import Button from '../common/Button'
import { InlineError, PersonOptions, inputCls, labelCls } from './lopUi'
import type { TeamPerson } from './lopTeam'
import { useLopWrite } from './useLopWrite'

export default function PinTopicDialog({ projectId, topic, people, teamError = null, onClose }: {
  projectId: number; topic: LopLine | null; people: TeamPerson[]; teamError?: string | null; onClose(): void
}) {
  const [resp, setResp] = useState('')
  const [due, setDue] = useState('')
  const [check, setCheck] = useState('')
  const pin = useLopWrite(projectId, (body: PinBody) => lopApi.pin(projectId, topic!.ref_key!, body),
    { fallback: 'The topic could not be pinned.', onDone: () => close() })
  const close = () => { setResp(''); setDue(''); setCheck(''); pin.clearError(); onClose() }
  const body: PinBody = {}
  if (resp) body.responsible_id = Number(resp)
  if (due) body.due_date = due
  if (check) body.next_check_date = check
  const ready = !!(due || check)
  const [first] = (topic?.text ?? '').split('\n')
  return (
    <Dialog open={topic !== null} onClose={close} busy={pin.pending} closeOnBackdrop={false} title="Pin PDB topic"
      description={topic ? `${topic.tool_number ? `${topic.tool_number} · ` : ''}${first}` : undefined}
      footer={(
        <>
          <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
          <Button size="sm" variant="primary" disabled={!ready} loading={pin.pending} onClick={() => pin.run(body)}>Pin topic</Button>
        </>
      )}>
      <div className="flex flex-col gap-2">
        <label className={labelCls}>Responsible
          <select className={inputCls} value={resp} onChange={(e) => setResp(e.target.value)} data-autofocus>
            <option value="">department only</option>
            <PersonOptions people={people} />
          </select>
        </label>
        {teamError && <InlineError>{teamError}</InlineError>}
        <div className="flex gap-2">
          <label className={labelCls}>Due date
            <input type="date" className={inputCls} value={due} onChange={(e) => setDue(e.target.value)} />
          </label>
          <label className={labelCls}>Next check
            <input type="date" className={inputCls} value={check} onChange={(e) => setCheck(e.target.value)} />
          </label>
        </div>
        {!ready && <p className="text-[11px] text-slate-400">A pinned topic needs a due date or a next-check date.</p>}
        <InlineError>{pin.error}</InlineError>
      </div>
    </Dialog>
  )
}
