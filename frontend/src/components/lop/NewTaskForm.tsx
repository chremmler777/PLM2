/** "+ Task": the PM adds an own task (title, department, responsible, due date). */
import { useState } from 'react'
import { lopApi, type TeamRow } from '../../api/lop'
import type { LineCreate } from '../../types/lop'
import { btnSm } from '../common/buttonStyles'
import { InlineError, PersonOptions, inputCls, labelCls } from './lopUi'
import type { TeamPerson } from './lopTeam'
import { useLopWrite } from './useLopWrite'

export default function NewTaskForm({ projectId, team, people, teamError = null, onDone }: {
  projectId: number; team: TeamRow[]; people: TeamPerson[]; teamError?: string | null; onDone(): void
}) {
  const [title, setTitle] = useState('')
  const [dept, setDept] = useState('')
  const [resp, setResp] = useState('')
  const [due, setDue] = useState('')
  const create = useLopWrite(projectId, (body: LineCreate) => lopApi.createLine(projectId, body),
    { fallback: 'The task could not be added.', onDone, refreshPdb: false })
  const submit = () => {
    const body: LineCreate = { title: title.trim() }
    if (dept) body.department_id = Number(dept)
    if (resp) body.responsible_id = Number(resp)
    if (due) body.due_date = due
    create.run(body)
  }
  return (
    <form data-testid="lop-new-task" className="mb-2 rounded-md border border-slate-700 bg-slate-900/50 p-2.5"
      onSubmit={(e) => { e.preventDefault(); if (title.trim()) submit() }}>
      <div className="flex flex-wrap items-end gap-2">
        <label className={`${labelCls} min-w-[16rem] flex-1`}>Task
          <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus
            placeholder="What has to be done" />
        </label>
        <label className={labelCls}>Department
          <select className={inputCls} value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="">none</option>
            {team.map((r) => <option key={r.department_id} value={r.department_id}>{r.department_name}</option>)}
          </select>
        </label>
        <label className={labelCls}>Responsible
          <select className={inputCls} value={resp} onChange={(e) => setResp(e.target.value)}>
            <option value="">from department</option>
            <PersonOptions people={people} />
          </select>
        </label>
        <label className={labelCls}>Due date
          <input type="date" className={inputCls} value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <button type="submit" className={btnSm.primary} disabled={!title.trim() || create.pending}>Add task</button>
        <button type="button" className={btnSm.ghost} onClick={onDone}>Cancel</button>
      </div>
      {teamError && <InlineError>{teamError}</InlineError>}
      <InlineError>{create.error}</InlineError>
    </form>
  )
}
