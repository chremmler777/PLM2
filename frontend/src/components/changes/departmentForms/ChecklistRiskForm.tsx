/**
 * The risk form, opened from a checklist row: the row already says what the
 * risk is about, so the note starts from it. Type and severity stay a
 * deliberate pick, as in the department's risk strip.
 */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../../api/changes'
import { btnSm } from '../../common/buttonStyles'
import { apiErrorMessage } from '../../../lib/apiError'
import { t } from '../../../i18n/cmLabels'
import type { RiskSeverity, RiskType } from '../../../types/change'

const SEVERITIES: RiskSeverity[] = [1, 2, 3]

/** What a screen reader says for a rating button: the number and its weight. */
const SEVERITY_NAME: Record<RiskSeverity, string> = {
  1: 'Severity 1, lowest', 2: 'Severity 2, medium', 3: 'Severity 3, highest',
}

export default function ChecklistRiskForm({ changeId, departmentId, checklistKey, defaultNote, onDone }: {
  changeId: number; departmentId: number; checklistKey: string; defaultNote: string
  onDone: () => void
}) {
  const qc = useQueryClient()
  const [riskType, setRiskType] = useState('')
  const [severity, setSeverity] = useState<RiskSeverity>(2)
  const [note, setNote] = useState(defaultNote)
  const [failure, setFailure] = useState<string | null>(null)
  const { data } = useQuery({
    queryKey: ['risk-types', departmentId],
    queryFn: () => changesApi.riskTypes(departmentId),
    retry: false,
  })
  const raise = useMutation({
    mutationFn: () => changesApi.raiseConcern(changeId, {
      kind: 'risk', note: note.trim(), department_id: departmentId,
      risk_type: riskType as RiskType, severity, checklist_key: checklistKey,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', changeId, 'concerns'] })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      onDone()
    },
    onError: (e: unknown) => setFailure(apiErrorMessage(e, 'Could not raise the risk')),
  })
  const missing = [
    ...(riskType ? [] : [t('concern.missingType')]),
    ...(note.trim() ? [] : [t('concern.missingNote')]),
  ]
  return (
    <div className="mt-1 ml-6 space-y-1 rounded border border-amber-700/50 bg-amber-950/20 p-2">
      <div className="flex flex-wrap items-center gap-2">
        <select value={riskType} data-testid="check-risk-type" aria-label={t('risk.kind')}
          onChange={(e) => setRiskType(e.target.value)}
          className="bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100">
          <option value="">{t('risk.pickType')}</option>
          {(data?.items ?? []).map((i) => (
            <option key={i.key} value={i.key}>{i.label_en ?? i.key}</option>
          ))}
        </select>
        <span className="flex items-center gap-1" role="group" aria-label={t('risk.severity')}>
          <span aria-hidden="true" className="text-[11px] text-slate-400 mr-0.5">{t('risk.severity')}</span>
          {SEVERITIES.map((s) => (
            <button key={s} type="button" data-testid={`check-risk-sev-${s}`}
              aria-pressed={severity === s} aria-label={SEVERITY_NAME[s]}
              onClick={() => setSeverity(s)}
              className={`w-7 h-6 rounded border text-xs font-semibold ${severity === s
                ? 'border-amber-500 bg-amber-900 text-amber-100'
                : 'border-slate-600 bg-slate-900 text-slate-400 hover:text-slate-200'}`}>
              {s}
            </button>
          ))}
        </span>
      </div>
      <textarea value={note} rows={2} data-testid="check-risk-note" aria-label={t('risk.note')}
        onChange={(e) => setNote(e.target.value)}
        className="w-full bg-slate-900 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
      {failure && <p role="alert" className="text-xs text-red-300">{failure}</p>}
      <div className="flex gap-2">
        <button type="button" data-testid="check-risk-submit"
          disabled={missing.length > 0 || raise.isPending}
          title={missing.length > 0 ? t('concern.missing').replace('{x}', missing.join(', ')) : undefined}
          onClick={() => raise.mutate()}
          className={btnSm.primary}>
          {t('check.flagRisk')}
        </button>
        <button type="button" onClick={onDone}
          className="text-xs text-slate-400 hover:text-slate-200 px-1">{t('common.cancel')}</button>
        {/* A disabled Flag button says what it still needs, in plain sight. */}
        {missing.length > 0 && (
          <span data-testid="check-risk-missing" className="self-center text-[11px] text-slate-400">
            {t('concern.missing').replace('{x}', missing.join(', '))}
          </span>
        )}
      </div>
    </div>
  )
}
