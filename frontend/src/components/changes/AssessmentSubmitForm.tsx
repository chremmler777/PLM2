import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'
import { DEPARTMENT_FIELDS } from './departmentForms'
import ActivityChecklist from './departmentForms/ActivityChecklist'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const VERDICTS = ['feasible', 'feasible_with_conditions', 'not_feasible'] as const

export default function AssessmentSubmitForm({
  changeId, departmentId, departmentName, onDone, showEffort = true,
}: {
  changeId: number; departmentId: number; departmentName: string; onDone: () => void
  /** Effort is money's business: the assessment bucket asks feasibility only and
   *  leaves hours to costing. The API still accepts them from other callers. */
  showEffort?: boolean
}) {
  const qc = useQueryClient()
  const [verdict, setVerdict] = useState('')
  const [effort, setEffort] = useState('')
  const [conditions, setConditions] = useState('')
  const [notes, setNotes] = useState('')
  // Whatever this department's own questionnaire collects, verbatim.
  const [details, setDetails] = useState<Record<string, unknown>>({})
  const Fields = DEPARTMENT_FIELDS[departmentName]
  // A questionnaire that answers "not impacted" is a complete assessment on its
  // own: nothing is affected, so there is nothing further to ask.
  const notImpacted = !!Fields && details.impacted === false
  const submit = useMutation({
    mutationFn: () => changesApi.submitAssessment(changeId, {
      department_id: departmentId,
      // "Not impacted" is feasible by definition — nothing changes for us.
      verdict: notImpacted ? 'feasible' : verdict,
      ...(showEffort ? { effort_hours: parseFloat(effort) } : {}),
      conditions: conditions || undefined, notes: notes || undefined,
      // One envelope for everything the department answered: the checklist and,
      // where it has one, its own questionnaire.
      details,
    }),
    onSuccess: () => {
      toast.success(`${departmentName}: ${verdict}`)
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-routing', changeId] })
      onDone()
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Submit failed'),
  })
  const ready = notImpacted || (verdict !== ''
    && (!showEffort || (effort !== '' && parseFloat(effort) >= 0))
    && (!Fields || details.impacted !== undefined))
  return (
    <div className="border border-slate-700 rounded-lg p-3 space-y-2 text-sm">
      {Fields && <Fields value={details} onChange={setDetails} />}
      {/* The workbook's checklist: their catalog, off by default. Skipped once a
          questionnaire has said the department is not impacted at all. */}
      {!notImpacted && (
        <ActivityChecklist departmentId={departmentId} value={details} onChange={setDetails} />
      )}
      {/* Not impacted answers everything: the rest of the form would only ask
          about work that does not exist. */}
      {!notImpacted && (
      <div className="flex flex-wrap items-end gap-3">
        <div>
          <label htmlFor={`verdict-${departmentId}`} className="block text-xs text-slate-500 mb-1">
            {t('assessment.verdict')}
          </label>
          <select id={`verdict-${departmentId}`} value={verdict}
            onChange={(e) => setVerdict(e.target.value)}
            className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100">
            <option value="">—</option>
            {VERDICTS.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </div>
        {showEffort && (
          <div>
            <label htmlFor={`effort-${departmentId}`} className="block text-xs text-slate-500 mb-1">
              {t('effort.hours')}
            </label>
            <input id={`effort-${departmentId}`} type="number" min="0" step="0.25"
              value={effort} onChange={(e) => setEffort(e.target.value)}
              className="w-28 bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
          </div>
        )}
      </div>
      )}
      {!notImpacted && verdict === 'feasible_with_conditions' && (
        <div>
          <label htmlFor={`conditions-${departmentId}`} className="block text-xs text-slate-500 mb-1">
            {t('conditions')}
          </label>
          <input id={`conditions-${departmentId}`} type="text"
            value={conditions} onChange={(e) => setConditions(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
        </div>
      )}
      {!notImpacted && (
        <textarea rows={2} placeholder="Notes" value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
      )}
      <button data-testid="assessment-submit"
        disabled={!ready || submit.isPending} onClick={() => submit.mutate()}
        className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm disabled:opacity-50">
        {notImpacted ? t('pkg.submitNotImpacted') : t('assessment.submit')}
      </button>
    </div>
  )
}
