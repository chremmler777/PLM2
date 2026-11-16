/**
 * The LOP table: lines in groups (GROUP_ORDER), one inline editor open at a
 * time. The PDB topics group opens small: one line with the number of open
 * topics and how many are escalated, and a Show button. A PDB that cannot be
 * reached is said even while the group is small, so a missing PDB never looks
 * like "no topics". Opened, it lists the topics and "+ N more" when the server
 * left topics out.
 */
import { Fragment, useState } from 'react'
import type { TeamRow } from '../../api/lop'
import { GROUP_LABEL, groupLines, lineKey } from '../../lib/lop'
import type { LopGroup, LopLine, PdbResponse } from '../../types/lop'
import LopLineEditor from './LopLineEditor'
import LopLineRow, { type RowContext } from './LopLineRow'
import type { TeamPerson } from './lopTeam'

export interface PdbGroupState {
  /** False when the view or a filter leaves PDB topics out. */
  show: boolean
  loading: boolean
  error: string | null
  data: PdbResponse | undefined
  onShowAll(): void
}

const GROUP_TONE: Partial<Record<LopGroup, string>> = {
  overdue: 'text-red-300',
  waiting_check: 'text-amber-300',
  stale: 'text-amber-200',
}

const PDB_OPEN_KEY = 'plm2.lop.pdbTopicsOpen'

function readPdbOpen(): boolean {
  try { return window.localStorage.getItem(PDB_OPEN_KEY) === '1' } catch { return false }
}

function pdbMessage(p: PdbGroupState): string | null {
  if (p.error) return `PDB cannot be reached: ${p.error}`
  if (p.loading || !p.data) return 'Reading PDB…'
  if (!p.data.available) return `PDB cannot be reached${p.data.reason ? `: ${p.data.reason}` : ''}. PDB topics are missing from this list.`
  if (p.data.status && p.data.status.tool_count === 0) return 'No tools in TWOS/PDB yet.'
  return null
}

export default function LopTable({ lines, ctx, team, people, teamError = null, canComment, pdb }: {
  lines: LopLine[]
  ctx: RowContext
  team: TeamRow[]
  people: TeamPerson[]
  teamError?: string | null
  canComment(line: LopLine): boolean
  pdb: PdbGroupState
}) {
  const [open, setOpen] = useState<number | null>(null)
  const [pdbOpen, setPdbOpen] = useState(readPdbOpen)
  const togglePdb = () => setPdbOpen((v) => {
    try { window.localStorage.setItem(PDB_OPEN_KEY, v ? '0' : '1') } catch { /* private mode: not remembered */ }
    return !v
  })
  const groups = groupLines(lines)
  const columns = ctx.meeting ? 11 : 10
  const pdbGroup = groups.find((g) => g.group === 'pdb')
  const hidden = pdb.data?.available ? pdb.data.hidden ?? 0 : 0
  const message = pdb.show ? pdbMessage(pdb) : null
  // the PDB group is shown even when empty, so a missing PDB never looks like "no topics"
  const showPdbHeader = pdb.show && !pdbGroup

  const escalated = pdbGroup ? pdbGroup.lines.filter((l) => l.escalated).length : 0
  const header = (g: LopGroup, n: number, extra?: string) => (
    <tr className="border-t border-slate-600">
      <td colSpan={columns} className={`pb-1 pt-3 text-xs font-semibold ${GROUP_TONE[g] ?? 'text-slate-200'}`}>
        {GROUP_LABEL[g]} ({n})
        {g === 'pdb' && escalated > 0 && <span data-testid="lop-pdb-escalated" className="ml-2 font-normal text-red-300">{escalated} escalated</span>}
        {g === 'pdb' && <span className="ml-2 font-normal text-slate-400">live from PDB{pdbOpen ? ' · escalated first, then oldest' : ''}</span>}
        {g === 'pdb' && n > 0 && (
          <button type="button" onClick={togglePdb} aria-expanded={pdbOpen} data-testid="lop-pdb-toggle"
            className="ml-2 rounded border border-slate-600 px-2 py-0.5 text-[11px] font-normal text-slate-200 hover:border-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
            {pdbOpen ? 'Hide topics' : 'Show topics'}
          </button>
        )}
        {extra && <span className="ml-2 font-normal text-slate-400">{extra}</span>}
      </td>
    </tr>
  )

  return (
    <table className="w-full border-collapse text-xs" data-testid="lop-table">
      <thead>
        <tr className="text-left text-[11px] text-slate-400">
          <th className="w-8"><span className="sr-only">Open</span></th>
          <th className="py-1 pr-2 font-medium">#</th>
          <th className="py-1 pr-3 font-medium">Task</th>
          <th className="py-1 pr-3 font-medium">Source</th>
          <th className="py-1 pr-3 font-medium">Department</th>
          <th className="py-1 pr-3 font-medium">Responsible</th>
          <th className="py-1 pr-3 font-medium">Due</th>
          <th className="py-1 pr-3 font-medium">Status</th>
          <th className="py-1 pr-3 font-medium">Last comment</th>
          {ctx.meeting && <th className="py-1 pr-3 font-medium">Meeting</th>}
          <th className="py-1 font-medium"><span className="sr-only">Actions</span></th>
        </tr>
      </thead>
      {groups.map(({ group, lines: rows }) => (
        <tbody key={group} data-testid={group === 'pdb' ? 'lop-pdb-group' : `lop-group-${group}`}>
          {header(group, group === 'pdb' ? rows.length + hidden : rows.length)}
          {(group === 'pdb' && !pdbOpen ? [] : rows).map((line) => (
            <Fragment key={lineKey(line)}>
              <LopLineRow line={line} ctx={ctx} expanded={open != null && open === line.id}
                onToggle={() => setOpen((o) => (o === line.id ? null : line.id))} />
              {open != null && open === line.id && (
                <tr>
                  <td />
                  <td colSpan={columns - 1} className="pb-2 pr-1">
                    <LopLineEditor line={line} projectId={ctx.projectId} team={team} people={people} teamError={teamError} canComment={canComment(line)} />
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
          {group === 'pdb' && pdbOpen && hidden > 0 && (
            <tr className="border-t border-slate-700/60">
              <td />
              <td colSpan={columns - 1} className="py-1.5 text-slate-400">
                + {hidden} more
                <button type="button" onClick={pdb.onShowAll}
                  className="ml-2 rounded border border-slate-600 px-2 py-0.5 text-[11px] text-slate-200 hover:border-slate-400">
                  show all
                </button>
              </td>
            </tr>
          )}
          {group === 'pdb' && message && (
            <tr><td /><td colSpan={columns - 1} className={`py-1.5 ${pdb.loading ? 'text-slate-400' : 'text-amber-300'}`}>{message}</td></tr>
          )}
        </tbody>
      ))}
      {showPdbHeader && (
        <tbody data-testid="lop-pdb-group">
          {header('pdb', 0)}
          <tr>
            <td />
            <td colSpan={columns - 1} className={`py-1.5 ${message && !pdb.loading ? 'text-amber-300' : 'text-slate-400'}`}>
              {message ?? ((pdb.data?.topics?.length ?? 0) > 0
                ? 'No unpinned PDB topics: every open topic is pinned and listed above.'
                : 'No open PDB topics on this project’s tools.')}
            </td>
          </tr>
        </tbody>
      )}
      {groups.length === 0 && !showPdbHeader && (
        <tbody><tr><td colSpan={columns} className="py-4 text-center text-slate-400">No lines in this view.</td></tr></tbody>
      )}
    </table>
  )
}
