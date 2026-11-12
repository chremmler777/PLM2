/**
 * The project LOP (list of open points) the PM walks through in the weekly
 * meeting: the live PDB status on top, then view chips and filters, the PM's
 * buttons, and the grouped table. Pinned PDB topics are lines of the project
 * list (always there, in their normal group); /pdb adds live fields to them
 * and the unpinned topics, which sit in "PDB topics". Write controls follow
 * the server's flags (can_manage, can_report); the server enforces them.
 */
import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { downloadLopXlsx, getProjectLop, getTeam, lopApi, lopKeys, teamQueryKey } from '../../api/lop'
import { useAuth } from '../../contexts/AuthContext'
import { apiErrorMessage } from '../../lib/apiError'
import { withLiveTopics } from '../../lib/lop'
import type { LopKind, LopLine, LopView } from '../../types/lop'
import { btnSm } from '../common/buttonStyles'
import AddFromSepDialog from './AddFromSepDialog'
import LopTable from './LopTable'
import { MeetingButtons, MeetingStatus } from './LopMeetingBar'
import { useMeetingDetail } from './useMeetingDetail'
import NewTaskForm from './NewTaskForm'
import PdbStatusBox from './PdbStatusBox'
import PinTopicDialog from './PinTopicDialog'
import { InlineError, inputCls } from './lopUi'
import { teamPeople } from './lopTeam'
import { lopErrorMessage } from './useLopWrite'

const VIEWS: { view: LopView; label: string }[] = [
  { view: 'meeting', label: 'Meeting view' },
  { view: 'open', label: 'All open' },
  { view: 'closed', label: 'Closed' },
]

const SOURCES: { kind: LopKind; label: string }[] = [
  { kind: 'sep_item', label: 'SEP items' },
  { kind: 'risk', label: 'SEP risks' },
  { kind: 'task', label: 'PM tasks' },
  { kind: 'pdb_topic', label: 'PDB topics' },
]

const chipCls = (on: boolean) =>
  `rounded-full border px-2.5 py-0.5 text-xs ${on
    ? 'border-sky-500 bg-sky-900/40 font-medium text-sky-100'
    : 'border-slate-600 text-slate-300 hover:border-slate-400'}`

export default function LopPanel({ projectId }: { projectId: number }) {
  const { userId, actingAsUser } = useAuth()
  const me = actingAsUser?.id ?? userId ?? null
  const [view, setView] = useState<LopView>('meeting')
  const [dept, setDept] = useState('')
  const [source, setSource] = useState<LopKind | ''>('')
  const [tool, setTool] = useState('')
  const [showAllPdb, setShowAllPdb] = useState(false)
  const [adding, setAdding] = useState(false)
  const [sepOpen, setSepOpen] = useState(false)
  const [pinning, setPinning] = useState<LopLine | null>(null)
  const [exportError, setExportError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)

  const lop = useQuery({ queryKey: lopKeys.project(projectId, view), queryFn: () => getProjectLop(projectId, view) })
  const pdbOn = view !== 'closed'
  const pdb = useQuery({
    queryKey: lopKeys.pdb(projectId, showAllPdb),
    queryFn: () => lopApi.pdb(projectId, showAllPdb),
    enabled: pdbOn && !!lop.data,
  })
  const team = useQuery({ queryKey: teamQueryKey(projectId), queryFn: () => getTeam(projectId) })
  const teamRows = useMemo(() => (Array.isArray(team.data) ? team.data : []), [team.data])
  const people = useMemo(() => teamPeople(teamRows), [teamRows])
  const data = lop.data
  const meetingDetail = useMeetingDetail(projectId, data)
  const teamError = team.isError
    ? `The project team could not be loaded: ${lopErrorMessage(team.error, 'no answer from the server')}`
    : null

  const all = useMemo(() => {
    const lines = data?.lines ?? []
    return withLiveTopics(lines, pdbOn && pdb.data?.available ? pdb.data.topics ?? [] : null)
  }, [data, pdb.data, pdbOn])

  if (lop.isLoading) return <p className="text-xs text-slate-400">Loading the LOP…</p>
  if (lop.isError) return <InlineError>{lopErrorMessage(lop.error, 'The LOP could not be loaded.')}</InlineError>
  if (!data) return <p className="text-xs text-slate-400">This project has no LOP.</p>

  const departments = [...new Set(all.map((l) => l.department_name ?? l.pdb_department).filter((d): d is string => !!d))].sort()
  const tools = [...new Set(all.map((l) => l.tool_number).filter((t): t is string => !!t))].sort()
  const shown = all.filter((l) =>
    (!dept || (l.department_name ?? l.pdb_department) === dept)
    && (!source || l.kind === source)
    && (!tool || l.tool_number === tool))
  const openMeeting = data.meeting?.open ? data.meeting : null
  const teamIds = new Set(people.map((p) => p.id))
  const canComment = (line: LopLine) =>
    line.can_manage || line.can_report || (me != null && (teamIds.has(me) || line.responsible_id === me))
  const pm = data.can_manage

  const exportXlsx = async () => {
    setExportError(null)
    setExporting(true)
    try {
      await downloadLopXlsx(projectId, view)
    } catch (e) {
      setExportError(apiErrorMessage(e, 'The Excel file could not be made.'))
    } finally {
      setExporting(false)
    }
  }

  return (
    <div data-testid="lop-panel" className="flex flex-col">
      {pdbOn && (
        <PdbStatusBox
          pdb={pdb.data}
          loading={pdb.isLoading}
          error={pdb.isError ? lopErrorMessage(pdb.error, 'no answer') : null}
        />
      )}

      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <div role="group" aria-label="View" className="flex gap-1">
          {VIEWS.map((v) => (
            <button key={v.view} type="button" aria-pressed={view === v.view} className={chipCls(view === v.view)}
              onClick={() => setView(v.view)}>
              {v.label}{v.view === 'open' && view !== 'closed' ? ` (${all.filter((l) => l.id != null).length})` : ''}
            </button>
          ))}
        </div>
        <select aria-label="Department" className={inputCls} value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="">Department: all</option>
          {departments.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select aria-label="Source" className={inputCls} value={source} onChange={(e) => setSource(e.target.value as LopKind | '')}>
          <option value="">Source: all</option>
          {SOURCES.map((s) => <option key={s.kind} value={s.kind}>{s.label}</option>)}
        </select>
        {tools.length > 0 && (
          <select aria-label="Tool" className={inputCls} value={tool} onChange={(e) => setTool(e.target.value)}>
            <option value="">Tool: all</option>
            {tools.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <span className="flex-1" />
        {pm && <button type="button" className={btnSm.secondary} onClick={() => setAdding((a) => !a)} aria-expanded={adding}>+ Task</button>}
        {pm && <button type="button" className={btnSm.secondary} onClick={() => setSepOpen(true)}>Add from SEP</button>}
        <MeetingButtons projectId={projectId} data={data} detail={meetingDetail.data} />
        <button type="button" className={btnSm.ghost} disabled={exporting} onClick={() => void exportXlsx()}>Excel</button>
      </div>
      <InlineError>{exportError}</InlineError>

      <MeetingStatus data={data} detail={meetingDetail.data} detailError={meetingDetail.isError ? meetingDetail.error : null} />
      {pm && adding && <NewTaskForm projectId={projectId} team={teamRows} people={people} teamError={teamError} onDone={() => setAdding(false)} />}

      <LopTable
        lines={shown}
        ctx={{ projectId, me, meeting: openMeeting, onPin: setPinning }}
        team={teamRows}
        people={people}
        teamError={teamError}
        canComment={canComment}
        pdb={{
          show: pdbOn && (!source || source === 'pdb_topic') && !tool && !dept,
          loading: pdb.isLoading,
          error: pdb.isError ? lopErrorMessage(pdb.error, 'no answer') : null,
          data: pdb.data,
          onShowAll: () => setShowAllPdb(true),
        }}
      />

      {pm && <AddFromSepDialog projectId={projectId} open={sepOpen} onClose={() => setSepOpen(false)} />}
      <PinTopicDialog projectId={projectId} topic={pinning} people={people} teamError={teamError} onClose={() => setPinning(null)} />
    </div>
  )
}
