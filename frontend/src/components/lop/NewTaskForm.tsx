/**
 * "+ Task": the PM adds an own task. A short title (one line, 500 characters),
 * optional details (goal, steps, done-when), department, responsible, due
 * date, and files dropped onto the form. The files are attached right after
 * the task is created; if that fails the task stays and the form says so.
 */
import { useState } from 'react'
import { lopApi, type TeamRow } from '../../api/lop'
import { formatBytes } from '../../api/sepFiles'
import { LOP_DETAILS_MAX, LOP_TITLE_MAX, type LineCreate } from '../../types/lop'
import { btnSm } from '../common/buttonStyles'
import { FileDrop } from './LopFiles'
import { InlineError, OwnersPicker, PersonOptions, inputCls, labelCls } from './lopUi'
import type { TeamPerson } from './lopTeam'
import { lopErrorMessage, useLopWrite } from './useLopWrite'

export default function NewTaskForm({ projectId, team, people, teamError = null, onDone }: {
  projectId: number; team: TeamRow[]; people: TeamPerson[]; teamError?: string | null; onDone(): void
}) {
  const [title, setTitle] = useState('')
  const [details, setDetails] = useState('')
  const [dept, setDept] = useState('')
  const [resp, setResp] = useState('')
  const [due, setDue] = useState('')
  const [owners, setOwners] = useState<number[]>([])
  const [files, setFiles] = useState<File[]>([])
  const [fileError, setFileError] = useState<string | null>(null)
  const create = useLopWrite(projectId, async (body: LineCreate) => {
    const line = await lopApi.createLine(projectId, body)
    if (files.length > 0 && line.id != null) {
      try {
        await lopApi.attachFiles(line.id, files)
      } catch (e) {
        // the task exists: keep the form open with the reason, do not create it twice
        setFileError(`The task was added, but the files were not attached: ${lopErrorMessage(e, 'upload failed')}. `
          + 'Open the task and attach them there.')
        return { line, filesFailed: true }
      }
    }
    return { line, filesFailed: false }
  }, { fallback: 'The task could not be added.', onDone: (r) => { if (!r.filesFailed) onDone() }, refreshPdb: false })

  const tooLong = title.trim().length > LOP_TITLE_MAX
  const detailsTooLong = details.trim().length > LOP_DETAILS_MAX
  const added = fileError != null
  const submit = () => {
    const body: LineCreate = { title: title.trim() }
    if (details.trim()) body.details = details.trim()
    if (dept) body.department_id = Number(dept)
    if (resp) body.responsible_id = Number(resp)
    if (due) body.due_date = due
    const more = owners.filter((id) => String(id) !== resp)
    if (more.length > 0) body.additional_owner_ids = more
    create.run(body)
  }
  const blocked = !title.trim() || tooLong || detailsTooLong || create.pending || added
  return (
    <form data-testid="lop-new-task" className="mb-2 rounded-md border border-slate-700 bg-slate-900/50 p-2.5"
      onSubmit={(e) => { e.preventDefault(); if (!blocked) submit() }}>
      <div className="flex flex-wrap items-end gap-2">
        <label className={`${labelCls} min-w-[16rem] flex-1`}>Task
          <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} autoFocus
            aria-invalid={tooLong} placeholder="What has to be done, in one line" />
        </label>
        <label className={labelCls}>Department
          <select className={inputCls} value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="">none</option>
            {team.map((r) => <option key={r.department_id} value={r.department_id}>{r.department_name}</option>)}
          </select>
        </label>
        <label className={labelCls} title="The main owner: the task counts for this person and their department">Responsible
          <select className={inputCls} value={resp} onChange={(e) => setResp(e.target.value)}>
            <option value="">from department</option>
            <PersonOptions people={people} />
          </select>
        </label>
        <OwnersPicker testId="lop-new-task-owners" people={people} value={owners}
          mainId={resp ? Number(resp) : null} onChange={setOwners} />
        <label className={labelCls}>Due date
          <input type="date" className={inputCls} value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <button type="submit" className={btnSm.primary} disabled={blocked}>Add task</button>
        <button type="button" className={btnSm.ghost} onClick={onDone}>{added ? 'Close' : 'Cancel'}</button>
      </div>
      {tooLong && (
        <InlineError>
          The task line is too long: {title.trim().length} of {LOP_TITLE_MAX} characters. Keep it to one line and put the rest into Details.
        </InlineError>
      )}
      <label className={`${labelCls} mt-2`}>Details (optional)
        <textarea rows={3} className={`${inputCls} h-auto py-1`} value={details} onChange={(e) => setDetails(e.target.value)}
          aria-invalid={detailsTooLong} placeholder="Goal, steps, when it is done" />
      </label>
      {detailsTooLong && (
        <InlineError>
          The details are too long: {details.trim().length} of {LOP_DETAILS_MAX} characters. Attach the rest as a file.
        </InlineError>
      )}
      <div className="mt-2">
        <FileDrop testId="lop-new-task-drop" busy={create.pending}
          onFiles={(picked) => setFiles((old) => [...old, ...picked])} />
        {files.length > 0 && (
          <ul className="mt-1 flex flex-wrap gap-1.5" aria-label="Files to attach">
            {files.map((f, i) => (
              <li key={`${f.name}-${i}`} className="flex items-center gap-1 rounded border border-slate-600 px-1.5 py-0.5 text-[11px] text-slate-200">
                {f.name} <span className="text-slate-500">{formatBytes(f.size)}</span>
                <button type="button" aria-label={`Do not attach ${f.name}`} disabled={create.pending || added}
                  className="text-slate-500 hover:text-red-300" onClick={() => setFiles((old) => old.filter((_, j) => j !== i))}>✕</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {teamError && <InlineError>{teamError}</InlineError>}
      <InlineError>{fileError ?? create.error}</InlineError>
    </form>
  )
}
