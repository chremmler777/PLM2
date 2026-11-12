/**
 * One line of the LOP table, with the one-click actions: Assign to me,
 * Confirm name, Confirm / Reopen a done line (PM), Done, please check (the
 * responsible), Discussed / Escalate during a meeting, Pin an open PDB topic.
 */
import { ChevronDown, ChevronRight, Pin } from 'lucide-react'
import { lopApi } from '../../api/lop'
import { MARK_LABEL, STATUS_LABEL, dueLabel, escalationLabel, pdbTopicUrl, shortDay, sourceLabel, sourceTone } from '../../lib/lop'
import type { LinePatch, LopLine, LopMeetingRef, MeetingMark } from '../../types/lop'
import { btnSm } from '../common/buttonStyles'
import { DefaultMarker, InlineError } from './lopUi'
import { useLopWrite } from './useLopWrite'

export interface RowContext {
  projectId: number
  me: number | null
  /** The open meeting, when one runs. */
  meeting: LopMeetingRef | null
  onPin(line: LopLine): void
}

function TaskCell({ line }: { line: LopLine }) {
  const [first, ...rest] = (line.text ?? line.title ?? '').split('\n')
  const more = rest.join(' ').trim()
  return (
    <div className="min-w-0">
      <div className="text-slate-100">
        {line.pinned && (
          <span data-testid="pin-marker" title="Pinned PDB topic" className="mr-1 inline-flex align-[-2px] text-violet-300">
            <Pin size={12} aria-label="Pinned PDB topic" />
          </span>
        )}
        {line.tool_number && <span className="font-semibold tabular-nums">{line.tool_number} · </span>}
        {first}
      </div>
      {more && <div className="text-[11px] text-slate-400">{more}</div>}
      {line.kind === 'risk' && line.source_context && <div className="text-[11px] text-slate-400">Risk: {line.source_context}</div>}
    </div>
  )
}

function DueCell({ line }: { line: LopLine }) {
  if (line.kind === 'pdb_topic' && !line.pinned) {
    const esc = escalationLabel(line.escalation_level)
    return (
      <span className="whitespace-nowrap">
        {esc && <span className={`mr-1 rounded px-1.5 text-[11px] ${line.escalated ? 'bg-red-900/60 text-red-100' : 'bg-amber-800/50 text-amber-100'}`}>{esc}</span>}
        {line.age_days != null ? `${line.age_days} d open` : 'age unknown'}
      </span>
    )
  }
  const lateDue = line.days_late > 0
  const missedCheck = line.late && !lateDue
  return (
    <div className="whitespace-nowrap">
      {line.moved && line.first_due_date && line.due_date && (
        <span data-testid="first-due" className="mr-1 text-[11px] text-slate-500 line-through">{shortDay(line.first_due_date)}</span>
      )}
      <span className={lateDue ? 'font-semibold text-red-300' : line.due_date ? 'text-slate-200' : 'text-slate-500'}>{dueLabel(line)}</span>
      {line.due_is_default && line.due_date && <DefaultMarker testId="default-due" title="Gate target date, not yet set by the PM" />}
      {line.next_check_date && (
        <div className={`text-[11px] ${missedCheck ? 'font-semibold text-red-300' : 'text-slate-400'}`}>
          check {shortDay(line.next_check_date)}{missedCheck ? ' · missed' : ''}
        </div>
      )}
    </div>
  )
}

function ResponsibleCell({ line }: { line: LopLine }) {
  if (line.kind === 'pdb_topic' && !line.pinned) return <span className="text-slate-500">department only</span>
  if (!line.responsible_name) return <span className="font-medium text-amber-300">no name</span>
  return (
    <span>
      {line.responsible_name}
      {line.responsible_is_default && <DefaultMarker testId="default-name" title="No team member for this department: the PM by default" />}
    </span>
  )
}

export default function LopLineRow({ line, ctx, expanded, onToggle }: {
  line: LopLine; ctx: RowContext; expanded: boolean; onToggle(): void
}) {
  const id = line.id
  const patch = useLopWrite(ctx.projectId, (body: LinePatch) => lopApi.patchLine(id!, body))
  const mark = useLopWrite(ctx.projectId, (m: MeetingMark) => lopApi.setMark(ctx.meeting!.id, id!, m))
  const unpinned = line.kind === 'pdb_topic' && !line.pinned
  const pm = line.can_manage
  const actions = []
  if (pm && unpinned) {
    const what = (line.text ?? '').split('\n')[0]
    actions.push(<button key="pin" type="button" className={btnSm.secondary} onClick={() => ctx.onPin(line)}
      aria-label={`Pin topic ${line.tool_number ?? ''} ${what}`.replace(/\s+/g, ' ').trim()}>Pin</button>)
  }
  if (pm && id != null && line.status !== 'closed') {
    if (ctx.me != null && line.responsible_id !== ctx.me) {
      actions.push(<button key="me" type="button" className={btnSm.ghost} disabled={patch.pending}
        aria-label={`Assign line ${id} to me`} onClick={() => patch.run({ responsible_id: ctx.me! })}>Assign to me</button>)
    }
    if (line.responsible_is_default && line.responsible_id != null) {
      actions.push(<button key="cn" type="button" className={btnSm.ghost} disabled={patch.pending}
        aria-label={`Confirm the responsible of line ${id}`} onClick={() => patch.run({ responsible_id: line.responsible_id! })}>Confirm name</button>)
    }
    if (line.status === 'done_check' && line.kind !== 'pdb_topic') {
      actions.push(<button key="ok" type="button" className={btnSm.secondary} disabled={patch.pending}
        aria-label={`Confirm line ${id}`} onClick={() => patch.run({ status: 'closed' })}>Confirm</button>)
    }
    if (line.status === 'done_check') {
      actions.push(<button key="re" type="button" className={btnSm.ghost} disabled={patch.pending}
        aria-label={`Reopen line ${id}`} onClick={() => patch.run({ status: 'open' })}>Reopen</button>)
    }
  }
  if (line.can_report && id != null && line.status !== 'done_check' && line.status !== 'closed') {
    actions.push(<button key="done" type="button" className={btnSm.secondary} disabled={patch.pending}
      aria-label={`Line ${id}: done, please check`} onClick={() => patch.run({ status: 'done_check' })}>Done, please check</button>)
  }
  const meetingMark = line.meeting_mark ?? 'none'
  const rowTestId = id != null ? `lop-row-${id}` : `lop-row-pdb-${line.ref_key}`
  return (
    <tr data-testid={rowTestId} className={`border-t border-slate-700/60 align-top ${expanded ? 'bg-slate-700/30' : ''}`}>
      <td className="w-8 py-1.5 pl-1 pr-1">
        {id != null && (
          <button type="button" onClick={onToggle} aria-expanded={expanded}
            aria-label={`${pm ? 'Edit line' : 'Open line'} ${id}`}
            className="inline-flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-700 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          </button>
        )}
      </td>
      <td className="py-1.5 pr-2 tabular-nums text-slate-500">{id ?? ''}</td>
      <td className="max-w-[28rem] py-1.5 pr-3"><TaskCell line={line} /></td>
      <td className="py-1.5 pr-3">
        <span className={`inline-block whitespace-nowrap rounded border px-1.5 text-[11px] ${sourceTone(line.kind)}`}>{sourceLabel(line)}</span>
        {pdbTopicUrl(line) && (
          <a data-testid="pdb-jump" href={pdbTopicUrl(line) as string} target="_blank" rel="noreferrer"
            title="Open this topic in PDB to work on it" onClick={(e) => e.stopPropagation()}
            className="ml-1.5 whitespace-nowrap text-[11px] text-violet-300 underline decoration-dotted underline-offset-2 hover:text-violet-200">
            Open in PDB ↗
          </a>
        )}
      </td>
      <td className="py-1.5 pr-3 text-slate-300">{line.department_name ?? line.pdb_department ?? ''}</td>
      <td className="py-1.5 pr-3 text-slate-200"><ResponsibleCell line={line} /></td>
      <td className="py-1.5 pr-3"><DueCell line={line} /></td>
      <td className="whitespace-nowrap py-1.5 pr-3">
        <span className={line.status === 'done_check' ? 'font-medium text-amber-300' : 'text-slate-300'}>
          {STATUS_LABEL[line.status]}
        </span>
        {line.handover_impact && <span className="text-[11px] text-slate-400"> · blocks handover</span>}
      </td>
      <td className="max-w-[16rem] py-1.5 pr-3 text-slate-400">
        {line.last_comment ? <span className="line-clamp-2" title={line.last_comment.text}>{line.last_comment.text}</span>
          : line.committed_until ? <span>committed until {shortDay(line.committed_until)}</span> : null}
      </td>
      {ctx.meeting && (
        <td className="whitespace-nowrap py-1.5 pr-3">
          {id != null && (
            <>
              <span data-testid="meeting-mark"
                className={meetingMark === 'none' ? 'text-amber-300' : meetingMark === 'escalated' ? 'text-red-300' : 'text-emerald-300'}>
                {MARK_LABEL[meetingMark]}
              </span>
              {pm && meetingMark === 'none' && (
                <button type="button" className={`${btnSm.ghost} ml-1`} disabled={mark.pending}
                  aria-label={`Mark line ${id} as discussed`} onClick={() => mark.run('updated')}>Discussed</button>
              )}
              {pm && meetingMark !== 'escalated' && (
                <button type="button" className={`${btnSm.ghost} ml-1`} disabled={mark.pending}
                  aria-label={`Escalate line ${id}`} onClick={() => mark.run('escalated')}>Escalate</button>
              )}
            </>
          )}
        </td>
      )}
      <td className="py-1.5 pr-1">
        <div className="flex flex-wrap justify-end gap-1">{actions}</div>
        <InlineError>{patch.error ?? mark.error}</InlineError>
      </td>
    </tr>
  )
}
