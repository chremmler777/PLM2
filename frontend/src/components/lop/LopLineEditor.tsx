/**
 * The inline editor under a line. The PM sets title (PM tasks), department,
 * responsible, due date and next check, and moves the status; moving an
 * existing due date needs a reason, a next-check date does not. Team members
 * comment; everyone reads the history.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { lopApi, lopKeys, type TeamRow } from '../../api/lop'
import { shortDay } from '../../lib/lop'
import type { LinePatch, LopHistoryItem, LopLine } from '../../types/lop'
import { btnSm } from '../common/buttonStyles'
import { InlineError, PersonOptions, inputCls, labelCls } from './lopUi'
import type { TeamPerson } from './lopTeam'
import { useLopWrite } from './useLopWrite'

const FIELD_LABEL: Record<string, string> = {
  due_date: 'due date', next_check_date: 'next check', status: 'status', responsible: 'responsible',
  department: 'department', title: 'title',
}

function historyText(h: LopHistoryItem): string {
  if (h.type === 'comment') return h.text
  const field = FIELD_LABEL[h.field] ?? h.field.replace(/_/g, ' ')
  const fmt = (v: string | null) => (v && /^\d{4}-\d{2}-\d{2}$/.test(v) ? shortDay(v) : v || 'none')
  return `${field}: ${fmt(h.old_value)} → ${fmt(h.new_value)}${h.reason ? ` (${h.reason})` : ''}`
}

function PmForm({ line, projectId, team, people }: {
  line: LopLine; projectId: number; team: TeamRow[]; people: TeamPerson[]
}) {
  const [title, setTitle] = useState(line.title ?? '')
  const [dept, setDept] = useState(line.department_id != null ? String(line.department_id) : '')
  const [resp, setResp] = useState(line.responsible_id != null ? String(line.responsible_id) : '')
  const [due, setDue] = useState(line.due_date ?? '')
  const [check, setCheck] = useState(line.next_check_date ?? '')
  const [reason, setReason] = useState('')
  const patch = useLopWrite(projectId, (body: LinePatch) => lopApi.patchLine(line.id!, body))

  const body: LinePatch = {}
  if (line.kind === 'task' && title.trim() !== (line.title ?? '')) body.title = title.trim()
  if (dept !== (line.department_id != null ? String(line.department_id) : '')) body.department_id = dept ? Number(dept) : null
  if (resp !== (line.responsible_id != null ? String(line.responsible_id) : '')) {
    if (resp) body.responsible_id = Number(resp)
    else body.clear_responsible = true
  }
  if (due !== (line.due_date ?? '')) body.due_date = due || null
  if (check !== (line.next_check_date ?? '')) body.next_check_date = check || null
  const moving = 'due_date' in body && line.due_date != null
  if (moving && reason.trim()) body.reason = reason.trim()
  const changed = Object.keys(body).filter((k) => k !== 'reason').length > 0
  const blocked = !changed || (moving && !reason.trim()) || (line.kind === 'task' && !title.trim())

  const status = (s: LinePatch['status']) => patch.run({ status: s })
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-end gap-2">
        {line.kind === 'task' && (
          <label className={`${labelCls} min-w-[16rem] flex-1`}>Title
            <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
        )}
        <label className={labelCls}>Department
          <select className={inputCls} value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="">none</option>
            {team.map((r) => <option key={r.department_id} value={r.department_id}>{r.department_name}</option>)}
          </select>
        </label>
        <label className={labelCls}>Responsible
          <select className={inputCls} value={resp} onChange={(e) => setResp(e.target.value)}>
            <option value="">no name</option>
            <PersonOptions people={people} />
          </select>
        </label>
        <label className={labelCls}>Due date
          <input type="date" className={inputCls} value={due} onChange={(e) => setDue(e.target.value)} />
        </label>
        <label className={labelCls}>Next check
          <input type="date" className={inputCls} value={check} onChange={(e) => setCheck(e.target.value)} />
        </label>
        {moving && (
          <label className={`${labelCls} min-w-[14rem] flex-1`}>Reason for moving the date
            <input className={inputCls} value={reason} required maxLength={200}
              placeholder="Why the date moves" onChange={(e) => setReason(e.target.value)} />
          </label>
        )}
        <button type="button" className={btnSm.primary} disabled={blocked || patch.pending} onClick={() => patch.run(body)}>Save</button>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {(line.status === 'new' || line.status === 'open') && (
          <button type="button" className={btnSm.ghost} disabled={patch.pending} onClick={() => status('in_work')}>Mark in work</button>
        )}
        {line.kind === 'pdb_topic' ? (
          <span className="text-[11px] text-slate-400">A pinned topic is closed in PDB and closes here by itself.</span>
        ) : line.status === 'closed' ? (
          <button type="button" className={btnSm.ghost} disabled={patch.pending} onClick={() => status('open')}>Reopen</button>
        ) : (
          <button type="button" className={btnSm.secondary} disabled={patch.pending} onClick={() => status('closed')}>Close line</button>
        )}
      </div>
      <InlineError>{patch.error}</InlineError>
    </div>
  )
}

function Comments({ line, projectId, canComment }: { line: LopLine; projectId: number; canComment: boolean }) {
  const [text, setText] = useState('')
  const history = useQuery({ queryKey: lopKeys.history(projectId, line.id!), queryFn: () => lopApi.history(line.id!) })
  const add = useLopWrite(projectId, (t: string) => lopApi.comment(line.id!, t), { onDone: () => setText('') })
  return (
    <div className="flex flex-col gap-1.5">
      {canComment && (
        <div className="flex items-end gap-2">
          <label className={`${labelCls} flex-1`}>Comment
            <textarea rows={2} className={`${inputCls} h-auto py-1`} value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <button type="button" className={btnSm.secondary} disabled={!text.trim() || add.pending}
            onClick={() => add.run(text.trim())}>Add comment</button>
        </div>
      )}
      <InlineError>{add.error}</InlineError>
      {history.isError && <InlineError>The history could not be loaded.</InlineError>}
      {Array.isArray(history.data) && history.data.length > 0 && (
        <ol className="flex flex-col gap-0.5 text-[11px] text-slate-400" aria-label="History">
          {history.data.map((h) => (
            <li key={`${h.type}-${h.id}`}>
              <span className="text-slate-500">{shortDay(h.created_at)} · {h.user_name ?? 'system'}: </span>
              <span className={h.type === 'comment' ? 'text-slate-200' : ''}>{historyText(h)}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

export default function LopLineEditor({ line, projectId, team, people, canComment }: {
  line: LopLine; projectId: number; team: TeamRow[]; people: TeamPerson[]; canComment: boolean
}) {
  if (line.id == null) return null
  return (
    <div data-testid={`lop-editor-${line.id}`} className="flex flex-col gap-3 rounded-md border border-slate-700 bg-slate-900/50 p-2.5">
      {line.can_manage && line.source_closed && (
        <p className="text-[11px] text-slate-400">Its source is closed; the line follows it.</p>
      )}
      {line.can_manage && <PmForm key={`${line.id}-${line.last_update_at}`} line={line} projectId={projectId} team={team} people={people} />}
      <Comments line={line} projectId={projectId} canComment={canComment} />
    </div>
  )
}
