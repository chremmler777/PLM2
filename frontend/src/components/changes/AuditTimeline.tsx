import { useMemo, useState } from 'react'
import { Check, X } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { auditApi, type AuditEntry } from '../../api/audit'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import { formatDate, formatTime, parseApiDateTime } from '../../lib/format'
import { auditValueLabel, humanize } from '../../lib/humanLabels'

// Short codes the backend stores for a handful of fields, in words.
const FIELD_WORDS: Record<string, (v: string) => string> = {
  channel: (v) => (t(`channel.${v}`) === `channel.${v}` ? humanize(v) : t(`channel.${v}`)),
  decision: (v) => ({ proceed: t('meeting.proceed'), reject: t('meeting.reject'),
    needs_info: t('meeting.needsInfo') } as Record<string, string>)[v] ?? humanize(v),
  kind: humanize, phase: humanize, answer: humanize, origin: humanize, branch: humanize,
  rasic_letter: (v) => v,
}

// Turn a stored JSON value into a plain phrase: no braces, quotes or codes.
// Keys name their field, so a value reads by its field ("status: Scoping").
const humanValue = (v: unknown, field?: string): string => {
  if (v === null || v === undefined) return '-'
  if (Array.isArray(v)) return v.length ? v.map((x) => humanValue(x, field)).join(', ') : '(none)'
  if (typeof v === 'object') {
    // Empty fields say nothing: "concern id: -" is noise in a trail. An id
    // whose name travels with it ("department id" next to "department name")
    // is said once, by the name.
    const obj = v as Record<string, unknown>
    return Object.entries(obj)
      .filter(([, val]) => val !== null && val !== undefined && val !== '')
      .filter(([k]) => !(k.endsWith('_id') && obj[`${k.slice(0, -3)}_name`] != null))
      .map(([k, val]) => `${keyLabel(k)}: ${humanValue(val, k)}`)
      .join(', ')
  }
  const f = (field ?? '').toLowerCase()
  if (FIELD_WORDS[f] && typeof v === 'string') return FIELD_WORDS[f](v)
  // A bare record id reads as a reference, not as a quantity.
  if ((f.endsWith('_id') || f.endsWith('_ids')) && typeof v === 'number') return `#${v}`
  return auditValueLabel(field ?? null, String(v))
}

// "part id" reads "part" ("part: 3457-10", "meeting: #41"); "superseded
// assessment ids" reads "superseded assessments" ("#258, #259"). The value
// says it is a reference, the key names what it refers to.
const keyLabel = (k: string): string => {
  const words = humanize(k).toLowerCase()
  return k.endsWith('_ids') ? words.replace(/ ids$/, 's') : k.endsWith('_id') ? words.replace(/ id$/, '') : words
}

const parse = (s: string | null): unknown => {
  if (!s) return null
  try { return JSON.parse(s) } catch { return s }
}

// The field a bare value belongs to, read from the action ("status_changed").
const fieldOfAction = (action: string): string | undefined =>
  action.startsWith('status') ? 'status'
  : action.startsWith('verdict') ? 'verdict'
  : action.startsWith('priority') ? 'priority' : undefined

// A human sentence for what changed: "Captured → Scoping", "pads.pdf", or null.
// The backend's resolved values (part numbers for part ids) win for the new side.
const describeChange = (e: Pick<AuditEntry, 'action' | 'old_values' | 'new_values' | 'display_values'>): string | null => {
  const field = fieldOfAction(e.action)
  const o = parse(e.old_values)
  const n = e.display_values && typeof e.display_values === 'object' ? e.display_values : parse(e.new_values)
  const hasO = o !== null && o !== undefined
  const hasN = n !== null && n !== undefined
  if (hasO && hasN) return `${humanValue(o, field)} → ${humanValue(n, field)}`
  if (hasN) return humanValue(n, field)
  if (hasO) return humanValue(o, field)
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
  // The memo a step was taken with (back to scoping, superseded answers ...)
  // lives on the change's own log, not in the audit row: same key as the page.
  const { data: changelog = [] } = useQuery({
    queryKey: ['change', changeId, 'changelog'],
    queryFn: () => changesApi.changelog(changeId!),
    enabled: changeId != null,
  })
  const reasonOf = (e: AuditEntry): string | null => {
    if (e.entity_type !== 'change') return null
    const at = parseApiDateTime(e.timestamp).getTime()
    const row = changelog.find((c) => c.action === e.action && !!c.notes?.trim()
      && Math.abs(parseApiDateTime(c.performed_at).getTime() - at) < 5000)
    return row?.notes?.trim() ?? null
  }

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
            <span data-testid="audit-chain" className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full ${
              !badge.ok ? 'bg-red-900 text-red-200'
              : 'warn' in badge && badge.warn ? 'bg-amber-900/70 text-amber-200'
              : 'bg-emerald-900 text-emerald-200'}`}>
              {badge.ok ? <Check aria-hidden="true" size={12} /> : <X aria-hidden="true" size={12} />}{badge.text}
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
              const detail = describeChange(e)
              const reason = reasonOf(e)
              return (
                <li key={e.id} className="text-sm flex flex-wrap items-baseline gap-x-2">
                  <span className="font-mono text-xs text-slate-500">
                    {formatTime(e.timestamp)}
                  </span>
                  <span className="font-medium text-slate-200">
                    {e.real_user_name ?? e.user_name ?? t('audit.system')}
                    {e.acting_as_department_name && (
                      <span data-testid="audit-acting" className="ml-1 font-normal text-xs text-amber-300/80">
                        {t('audit.actingAs').replace('{d}', e.acting_as_department_name)}
                      </span>
                    )}
                  </span>
                  <span className="text-slate-300">{humanize(e.action).toLowerCase()}</span>
                  {detail && <span className="text-slate-400">: {detail}</span>}
                  {reason && !(detail ?? '').includes(reason) && (
                    <span data-testid={`audit-reason-${e.id}`} className="text-slate-300">
                      ({t('audit.reason')}: {reason})
                    </span>
                  )}
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
