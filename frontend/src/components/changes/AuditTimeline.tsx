import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { auditApi, type AuditEntry } from '../../api/audit'
import { t } from '../../i18n/cmLabels'

const pretty = (s: string | null): string | null => {
  if (!s) return null
  try { return JSON.stringify(JSON.parse(s), null, 2) } catch { return s }
}

const LIST_LIMIT = 1000

export default function AuditTimeline({ correlationId }: { correlationId: string }) {
  const [entityFilter, setEntityFilter] = useState<string>('all')
  const { data: entries = [], isLoading } = useQuery({
    queryKey: ['audit', correlationId],
    // Newest-first (see backend's list ordering): with LIST_LIMIT truncation
    // this drops the OLDEST entries, keeping the most recent history visible.
    queryFn: () => auditApi.list({ correlation_id: correlationId, limit: LIST_LIMIT }),
  })
  // Always correlation-scoped: this component is always shown for one change,
  // so the chain check is run WITH correlation_id and the badge reports what
  // was actually verified for this change (not just "some global chain").
  const { data: chain } = useQuery({
    queryKey: ['audit-verify', correlationId],
    queryFn: () => auditApi.verify({ correlation_id: correlationId }),
  })
  const truncated = entries.length === LIST_LIMIT

  const entityTypes = useMemo(
    () => Array.from(new Set(entries.map((e) => e.entity_type))), [entries])
  const shown = useMemo(() => {
    const filtered = entityFilter === 'all' ? entries
      : entries.filter((e) => e.entity_type === entityFilter)
    return [...filtered].sort((a, b) => b.id - a.id)
  }, [entries, entityFilter])

  const byDay = useMemo(() => {
    const groups = new Map<string, AuditEntry[]>()
    for (const e of shown) {
      // Day grouping is computed in UTC (not the browser's local timezone) so
      // the heading is stable across viewers - suffixed "(UTC)" so it reads
      // unambiguously either way.
      const day = `${new Date(e.timestamp).toLocaleDateString(undefined, { timeZone: 'UTC' })} (UTC)`
      if (!groups.has(day)) groups.set(day, [])
      groups.get(day)!.push(e)
    }
    return Array.from(groups.entries())
  }, [shown])

  if (isLoading) return <div className="text-slate-400 text-sm">…</div>

  return (
    <div>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-200">{t('audit.title')}</h3>
          {chain && (
            <span className={`text-xs px-2 py-0.5 rounded-full ${
              chain.correlation_ok ? 'bg-emerald-900 text-emerald-200' : 'bg-red-900 text-red-200'}`}>
              {chain.correlation_ok
                ? `✓ ${t('audit.chainOkScoped')}`
                : `✗ ${t('audit.chainBrokenScoped')}`}
            </span>
          )}
        </div>
        <button
          className="text-xs border border-slate-600 text-slate-300 hover:bg-slate-700 px-3 py-1.5 rounded-lg"
          onClick={() => auditApi.downloadCsv({ correlation_id: correlationId })}>
          ⬇ {t('audit.export')}
        </button>
      </div>

      <div className="flex gap-1.5 mb-4 flex-wrap">
        {['all', ...entityTypes].map((et) => (
          <button key={et}
            className={`text-xs px-2.5 py-1 rounded-full ${
              entityFilter === et ? 'bg-sky-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
            onClick={() => setEntityFilter(et)}>
            {et === 'all' ? t('audit.all') : et}
          </button>
        ))}
      </div>

      {truncated && (
        <p className="text-xs text-amber-400 mb-3">{t('audit.truncated')}</p>
      )}

      {shown.length === 0 && <p className="text-sm text-slate-500">{t('audit.empty')}</p>}
      {byDay.map(([day, dayEntries]) => (
        <div key={day} className="mb-4">
          <h4 className="text-xs uppercase tracking-wide text-slate-500 mb-2">{day}</h4>
          <ol className="space-y-1.5 border-l border-slate-700 pl-4">
            {dayEntries.map((e) => (
              <li key={e.id} className="text-sm">
                <span className="font-mono text-xs text-slate-500 mr-2">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </span>
                <span className="text-slate-100">{e.action.replace(/_/g, ' ')}</span>
                <span className="ml-2 text-xs text-slate-500">{e.entity_type}#{e.entity_id}</span>
                {(e.old_values || e.new_values) && (
                  <details className="ml-6 mt-0.5">
                    <summary className="text-xs text-slate-500 cursor-pointer">details</summary>
                    <pre className="text-xs text-slate-400 bg-slate-900 rounded p-2 mt-1 overflow-x-auto">
{pretty(e.old_values) ? `- ${pretty(e.old_values)}\n` : ''}{pretty(e.new_values) ? `+ ${pretty(e.new_values)}` : ''}
                    </pre>
                  </details>
                )}
              </li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  )
}
