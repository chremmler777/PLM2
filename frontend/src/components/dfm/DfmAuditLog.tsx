/**
 * DfmAuditLog - the compact, newest-first audit trail table for one topic
 * (topicId given) or the whole tool (topicId absent). Filters by action
 * group are applied client-side over the loaded page, since the API filters
 * by a single action at a time. "Load older" pages with before_id. Each
 * message/file row's "#N" link hands the entry id back to the caller, which
 * switches to the flow and reuses its existing highlight.
 * Mirrors docs/superpowers/specs/2026-09-24-dfm-audit-api.md.
 */
import { useEffect, useState } from 'react';
import { getAudit, KIND_LABELS, PARTY_LABELS, dfmAuditCsvUrl, type DfmAuditEvent } from '../../api/dfm';
import { apiErrorMessage } from '../../lib/apiError';
import {
  AUDIT_ACTION_STYLE, AUDIT_GROUPS, AUDIT_GROUP_LABELS, auditFileSize, auditLocalTime, auditShaShort,
  matchesAuditGroup, type DfmAuditGroup,
} from './dfmAudit';

const PAGE_LIMIT = 100;

interface Props {
  partId: number;
  /** Scope to one topic; absent shows the tool-wide log with a topic column. */
  topicId?: number;
  onJumpToEntry(entryId: number, topicId: number): void;
}

export default function DfmAuditLog({ partId, topicId, onJumpToEntry }: Props) {
  const [events, setEvents] = useState<DfmAuditEvent[]>([]);
  const [group, setGroup] = useState<DfmAuditGroup>('all');
  const [hasMore, setHasMore] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (beforeId?: number) => {
    if (beforeId == null) setLoading(true); else setLoadingMore(true);
    try {
      const page = await getAudit(partId, { topicId, limit: PAGE_LIMIT, beforeId });
      setEvents((cur) => (beforeId == null ? page : [...cur, ...page]));
      setHasMore(page.length === PAGE_LIMIT);
      setError(null);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not load the audit log'));
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  };

  useEffect(() => {
    setEvents([]);
    setHasMore(true);
    void load(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [partId, topicId]);

  const loadOlder = () => {
    const last = events[events.length - 1];
    if (last) void load(last.id);
  };

  const shown = events.filter((e) => matchesAuditGroup(e.action, group));
  const csvHref = dfmAuditCsvUrl(partId, topicId);

  if (error) {
    return <p data-testid="dfm-audit-error" className="text-red-400 text-sm">{error}</p>;
  }

  return (
    <div data-testid="dfm-audit-log" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <select data-testid="dfm-audit-filter" value={group} onChange={(e) => setGroup(e.target.value as DfmAuditGroup)}
          className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs">
          {AUDIT_GROUPS.map((g) => <option key={g} value={g}>{AUDIT_GROUP_LABELS[g]}</option>)}
        </select>
        <a data-testid="dfm-audit-csv" href={csvHref} download
          className="ml-auto px-3 py-1 rounded-md bg-slate-700 hover:bg-slate-600 text-slate-100 text-xs">Export CSV</a>
      </div>

      {loading ? (
        <div className="text-slate-400 text-sm">Loading…</div>
      ) : shown.length === 0 ? (
        <p data-testid="dfm-audit-empty" className="text-slate-500 text-sm">No audit events{group !== 'all' ? ' for this filter' : ''}.</p>
      ) : (
        <div className="overflow-auto rounded-md ring-1 ring-slate-700">
          <table className="w-full text-xs">
            <thead className="bg-slate-900 sticky top-0">
              <tr className="text-slate-400 text-left">
                <th className="px-2 py-1.5 font-medium">Time</th>
                <th className="px-2 py-1.5 font-medium">User</th>
                <th className="px-2 py-1.5 font-medium">Action</th>
                {topicId === undefined && <th className="px-2 py-1.5 font-medium">Topic</th>}
                <th className="px-2 py-1.5 font-medium" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {shown.map((e) => <Row key={e.id} e={e} showTopic={topicId === undefined} onJumpToEntry={onJumpToEntry} />)}
            </tbody>
          </table>
        </div>
      )}

      {hasMore && (
        <button data-testid="dfm-audit-load-older" onClick={loadOlder} disabled={loadingMore}
          className="self-start px-3 py-1 rounded-md bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-100 text-xs">
          {loadingMore ? 'Loading…' : 'Load older'}
        </button>
      )}
    </div>
  );
}

function Row({ e, showTopic, onJumpToEntry }: { e: DfmAuditEvent; showTopic: boolean; onJumpToEntry(entryId: number, topicId: number): void }) {
  const style = AUDIT_ACTION_STYLE[e.action];
  const isMessage = e.action === 'entry_recorded' || e.action === 'entry_updated';
  const isFile = e.action === 'file_attached' || e.action === 'file_viewed' || e.action === 'file_downloaded';
  const sha = e.action === 'file_attached' ? auditShaShort(e.details.sha256) : null;
  const jumpable = e.entry != null && e.topic != null;

  return (
    <tr data-testid={`dfm-audit-row-${e.id}`} className="align-top hover:bg-slate-800/60">
      <td className="px-2 py-1.5 whitespace-nowrap tabular-nums text-slate-300">{auditLocalTime(e.at)}</td>
      <td className="px-2 py-1.5 whitespace-nowrap text-slate-300">{e.actor.name}</td>
      <td className="px-2 py-1.5">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className={`inline-flex items-center gap-1 text-[11px] font-medium px-1.5 py-px rounded ring-1 ring-inset ${style.badge}`}>
            <span aria-hidden className={`inline-block w-1.5 h-1.5 rounded-full ${style.dot}`} />
            {style.label}
          </span>
          {isMessage && e.details.kind && (
            <span data-testid="dfm-audit-kind" className="text-[11px] text-slate-300">{KIND_LABELS[e.details.kind]}</span>
          )}
          {isMessage && (
            <span className="text-slate-400">
              {e.details.party && PARTY_LABELS[e.details.party]}
              {' → '}
              {(e.details.addressed_to ?? []).map((p) => PARTY_LABELS[p]).join(', ')}
            </span>
          )}
          {isFile && (
            <span className="text-slate-300 font-mono break-all">{e.details.filename ?? e.file?.filename}</span>
          )}
          {e.action === 'file_attached' && e.details.size != null && (
            <span className="text-slate-500 tabular-nums">{auditFileSize(e.details.size)}</span>
          )}
          {sha && (
            <span data-testid="dfm-audit-sha" title={e.details.sha256 ?? undefined} className="text-slate-500 font-mono">{sha}</span>
          )}
          {e.details.backfilled && (
            <span data-testid="dfm-audit-reconstructed" title="rebuilt from existing data, views and downloads before the audit log existed are not recorded"
              className="text-[10px] px-1 py-px rounded ring-1 ring-inset ring-slate-500 text-slate-400">reconstructed</span>
          )}
        </div>
      </td>
      {showTopic && <td className="px-2 py-1.5 text-slate-400" data-testid="dfm-audit-topic">{e.topic ? `#${e.topic.id} ${e.topic.title}` : ''}</td>}
      <td className="px-2 py-1.5 text-right">
        {jumpable && (
          <button data-testid={`dfm-audit-jump-${e.entry!.id}`} onClick={() => onJumpToEntry(e.entry!.id, e.topic!.id)}
            className="text-blue-300 hover:underline">#{e.entry!.id}</button>
        )}
      </td>
    </tr>
  );
}
