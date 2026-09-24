/**
 * WorksheetAuditView - the worksheet's audit log: who commented, flagged or
 * changed which field of which part, newest first, from the part changelog.
 * A row opens the field where it is edited, as the cell menu's Edit does.
 */
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import type { AuditGroup, WorksheetAuditFilters } from '../../api/worksheet';
import { useWorksheetAudit } from '../../hooks/queries/useWorksheet';
import { apiErrorMessage } from '../../lib/apiError';
import { localDateTime } from '../../lib/fieldNotes';
import { WORKSHEET_COLUMNS } from './worksheetColumns';
import {
  AUDIT_GROUP_BADGE, AUDIT_GROUP_LABELS, AUDIT_GROUPS, auditActionText, auditEditPath, auditFieldLabel,
  auditValueChange, excerpt, worksheetAuditCsvUrl,
} from './worksheetAudit';

export interface WorksheetAuditViewProps {
  projectId: number;
}

const TEXT_DEBOUNCE_MS = 300;
const DESCRIPTION_EXCERPT = 80;

/** Field keys the changelog uses: the columns' keys, with Colour split into its two sources. */
const FIELD_OPTIONS: { key: string; label: string }[] = [
  ...WORKSHEET_COLUMNS
    .filter((c) => c.noteOwner !== null && c.key !== 'part.colour')
    .map((c) => ({ key: c.key, label: c.label })),
  { key: 'part.colour_code', label: 'Colour (MIC code)' },
  { key: 'paint.colour', label: 'Colour (paint)' },
];

export default function WorksheetAuditView({ projectId }: WorksheetAuditViewProps) {
  const navigate = useNavigate();
  const [group, setGroup] = useState<AuditGroup | ''>('');
  const [fieldKey, setFieldKey] = useState('');
  const [partText, setPartText] = useState('');
  const [part, setPart] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setPart(partText), TEXT_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [partText]);

  const filters: WorksheetAuditFilters = useMemo(
    () => ({ action_group: group, part, field_key: fieldKey }), [group, part, fieldKey]);
  const { data, isLoading, isError, error, fetchNextPage, hasNextPage, isFetchingNextPage } = useWorksheetAudit(projectId, filters);
  const entries = useMemo(() => data?.pages.flatMap((p) => p.entries) ?? [], [data]);

  const select = 'bg-slate-800 border border-slate-700 rounded px-1 py-0.5 text-slate-100';
  return (
    <div data-testid="worksheet-audit" className="h-full flex flex-col min-h-0">
      <div className="flex-shrink-0 flex flex-wrap items-center gap-3 px-3 py-2 border-b border-slate-800 text-xs text-slate-300">
        <label className="flex items-center gap-1">
          Group
          <select data-testid="audit-filter-group" value={group} onChange={(e) => setGroup(e.target.value as AuditGroup | '')} className={select}>
            <option value="">All</option>
            {AUDIT_GROUPS.map((g) => <option key={g} value={g}>{AUDIT_GROUP_LABELS[g]}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1">
          Part
          <input data-testid="audit-filter-part" value={partText} placeholder="KTX or OEM no."
            onChange={(e) => setPartText(e.target.value)} className={`${select} w-40 placeholder-slate-500`} />
        </label>
        <label className="flex items-center gap-1">
          Field
          <select data-testid="audit-filter-field" value={fieldKey} onChange={(e) => setFieldKey(e.target.value)} className={select}>
            <option value="">All</option>
            {FIELD_OPTIONS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
          </select>
        </label>
        <a data-testid="audit-export-csv" href={worksheetAuditCsvUrl(projectId, filters)} download
          className="px-2 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-white">Export CSV</a>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        {isLoading ? (
          <p className="p-4 text-sm text-slate-500">Loading...</p>
        ) : isError ? (
          <p data-testid="audit-error" className="p-4 text-sm text-red-400">{apiErrorMessage(error, 'Could not load the audit log')}</p>
        ) : entries.length === 0 ? (
          <p className="p-4 text-sm text-slate-500">No entries match</p>
        ) : (
          <table className="w-full text-xs border-separate border-spacing-0">
            <thead className="sticky top-0 z-10 bg-slate-900 text-left text-slate-400">
              <tr>
                {['Time', 'User', 'Part', 'Field', 'Action', 'Change', 'Description'].map((h) => (
                  <th key={h} className="px-2 py-1 font-medium whitespace-nowrap border-b border-slate-700">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} data-testid={`audit-row-${e.id}`} onClick={() => navigate(auditEditPath(e))}
                  title="Open this field" className="cursor-pointer hover:bg-slate-800/60 align-top">
                  <td className="px-2 py-1 border-b border-slate-800 whitespace-nowrap tabular-nums text-slate-300">{e.at ? localDateTime(e.at) : ''}</td>
                  <td className="px-2 py-1 border-b border-slate-800 whitespace-nowrap text-slate-200">{e.actor?.name ?? 'Unknown'}</td>
                  <td className="px-2 py-1 border-b border-slate-800 whitespace-nowrap font-mono text-slate-200">
                    {e.part.part_number}
                    {e.part.customer_part_number && <span className="text-slate-500"> / {e.part.customer_part_number}</span>}
                  </td>
                  <td className="px-2 py-1 border-b border-slate-800 whitespace-nowrap text-slate-200">{auditFieldLabel(e.field_key)}</td>
                  <td className="px-2 py-1 border-b border-slate-800 whitespace-nowrap">
                    <span data-testid={`audit-badge-${e.id}`} className={`inline-block px-1.5 rounded text-[10px] mr-1 ${AUDIT_GROUP_BADGE[e.action_group]}`}>
                      {AUDIT_GROUP_LABELS[e.action_group]}
                    </span>
                    <span className="text-slate-200">{auditActionText(e)}</span>
                  </td>
                  <td className="px-2 py-1 border-b border-slate-800 text-slate-200 break-words max-w-xs">{auditValueChange(e)}</td>
                  <td className="px-2 py-1 border-b border-slate-800 text-slate-400 break-words max-w-md" title={e.description}>
                    {excerpt(e.action === 'field_comment_added' ? e.new_value ?? e.description : e.description, DESCRIPTION_EXCERPT)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {hasNextPage && (
          <div className="p-2">
            <button type="button" data-testid="audit-load-older" disabled={isFetchingNextPage} onClick={() => fetchNextPage()}
              className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-xs text-slate-100">
              {isFetchingNextPage ? 'Loading...' : 'Load older'}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
