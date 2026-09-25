import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { auditApi, type AuditEntry } from '../../api/audit'
import { t } from '../../i18n/cmLabels'
import { formatDate, formatDateTime } from '../../lib/format'
import { auditValueLabel, humanize } from '../../lib/humanLabels'

// Turn a stored JSON value into a plain phrase: no braces, quotes or codes.
// Keys name their field, so a value reads by its field ("status: Scoping").
const humanValue = (v: unknown, field?: string): string => {
  if (v === null || v === undefined) return '-'
  if (Array.isArray(v)) return v.length ? v.map((x) => humanValue(x, field)).join(', ') : '(none)'
  if (typeof v === 'object') {
    // Empty fields say nothing: "concern id: -" is noise in a trail.
    return Object.entries(v as Record<string, unknown>)
      .filter(([, val]) => val !== null && val !== undefined && val !== '')
      .map(([k, val]) => `${humanize(k).toLowerCase()}: ${humanValue(val, k)}`)
      .join(', ')
  }
  return auditValueLabel(field ?? null, String(v))
}

const parse = (s: string | null): unknown => {
  if (!s) return null
  try { return JSON.parse(s) } catch { return s }
}

// A human sentence for what changed: "captured → scoping", "pads.pdf", or null.
const describeChange = (oldRaw: string | null, newRaw: string | null): string | null => {
  const o = parse(oldRaw)
  const n = parse(newRaw)
  const hasO = o !== null && o !== undefined
  const hasN = n !== null && n !== undefined
  if (hasO && hasN) return `${humanValue(o)} → ${humanValue(n)}`
  if (hasN) return humanValue(n)
  if (hasO) return humanValue(o)
  return null
}

const LIST_LIMIT = 1000

export default function AuditTimeline({ correlationId, changeId }: {
  correlationId: string
  /** The change's own trail by entity ids (spec §16 P1 9), not by number text. */
  changeId?: number
}) {
  const [entityFilter, setEntityFilter] = useState<string>('all')
  const scope = changeId != null ? { change_id: changeId } : { correlation_id: correlationId }
  const { data: entries = [], isLoading } = useQuery({
    queryKey: ['audit', correlationId, changeId ?? null],
    // Newest-first (see backend's list ordering): with LIST_LIMIT truncation
    // this drops the OLDEST entries, keeping the most recent history visible.
    queryFn: () => auditApi.list({ ...scope, limit: LIST_LIMIT }),
  })
  // Always scoped to this change, and the badge says which chain broke: a
  // break inside this change's entries is this change's problem; a break
  // elsewhere in the global chain is not.
  const { data: chain } = useQuery({
    queryKey: ['audit-verify', correlationId, changeId ?? null],
    queryFn: () => auditApi.verify({ correlation_id: correlationId, ...(changeId != null ? { change_id: changeId } : {}) }),
  })
  const badge = !chain ? null
    : chain.break_scope === 'change' ? {
      ok: false,
      text: t('audit.brokenInChange').replace('{n}', String(chain.change_first_broken_id ?? chain.first_broken_id ?? '?')),
    }
    : chain.break_scope === 'global' ? {
      ok: true, warn: true,
      text: t('audit.brokenGlobally').replace('{n}', String(chain.first_broken_id ?? '?')),
    }
    : chain.break_scope === 'none' ? { ok: true, text: t('audit.chainOkScoped') }
    // An older backend: correlation verdict only, still told apart from a global break.
    : chain.correlation_ok ? { ok: true, text: t('audit.chainOkScoped') }
    : chain.valid === false && chain.first_broken_id != null ? {
      ok: true, warn: true,
      text: t('audit.brokenGlobally').replace('{n}', String(chain.first_broken_id)),
    }
    : { ok: false, text: t('audit.chainBrokenScoped') }
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
      // Day grouping matches the row times below (both local): a local
      // midnight boundary keeps entries under the heading their time reads
      // under, instead of splitting across a UTC day boundary.
      const day = formatDate(e.timestamp)
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
          {badge && (
            <span data-testid="audit-chain" className={`text-xs px-2 py-0.5 rounded-full ${
              !badge.ok ? 'bg-red-900 text-red-200'
              : 'warn' in badge && badge.warn ? 'bg-amber-900/70 text-amber-200'
              : 'bg-emerald-900 text-emerald-200'}`}>
              {badge.ok ? '✓' : '✗'} {badge.text}
            </span>
          )}
        </div>
        <button
          className="text-xs border border-slate-600 text-slate-300 hover:bg-slate-700 px-3 py-1.5 rounded-lg"
          onClick={() => auditApi.downloadCsv(scope)}>
          ⬇ {t('audit.export')}
        </button>
      </div>

      <div className="flex gap-1.5 mb-4 flex-wrap">
        {['all', ...entityTypes].map((et) => (
          <button key={et}
            className={`text-xs px-2.5 py-1 rounded-full ${
              entityFilter === et ? 'bg-sky-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
            onClick={() => setEntityFilter(et)}>
            {et === 'all' ? t('audit.all') : humanize(et)}
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
            {dayEntries.map((e) => {
              const detail = describeChange(e.old_values, e.new_values)
              return (
                <li key={e.id} className="text-sm flex flex-wrap items-baseline gap-x-2">
                  <span className="font-mono text-xs text-slate-500">
                    {formatDateTime(e.timestamp).slice(11)}
                  </span>
                  <span className="font-medium text-slate-200">{e.user_name ?? t('audit.system')}</span>
                  <span className="text-slate-300">{humanize(e.action).toLowerCase()}</span>
                  {detail && <span className="text-slate-400">: {detail}</span>}
                  <span className="text-xs text-slate-600">{humanize(e.entity_type)} {e.entity_id}</span>
                </li>
              )
            })}
          </ol>
        </div>
      ))}
    </div>
  )
}
