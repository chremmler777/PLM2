import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { t } from '../../i18n/cmLabels'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const VERDICTS = ['feasible', 'feasible_with_conditions', 'not_feasible'] as const

export default function AssessmentSubmitForm({ changeId, departmentId, departmentName, onDone }: {
  changeId: number; departmentId: number; departmentName: string; onDone: () => void
}) {
  const qc = useQueryClient()
  const [verdict, setVerdict] = useState('')
  const [effort, setEffort] = useState('')
  const [conditions, setConditions] = useState('')
  const [notes, setNotes] = useState('')
  const submit = useMutation({
    mutationFn: () => changesApi.submitAssessment(changeId, {
      department_id: departmentId, verdict,
      effort_hours: parseFloat(effort),
      conditions: conditions || undefined, notes: notes || undefined,
    }),
    onSuccess: () => {
      toast.success(`${departmentName}: ${verdict}`)
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change-routing', changeId] })
      onDone()
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Submit failed'),
  })
  const ready = verdict !== '' && effort !== '' && parseFloat(effort) >= 0
  return (
    <div className="border border-slate-700 rounded-lg p-3 space-y-2 text-sm">
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
        <div>
          <label htmlFor={`effort-${departmentId}`} className="block text-xs text-slate-500 mb-1">
            {t('effort.hours')}
          </label>
          <input id={`effort-${departmentId}`} type="number" min="0" step="0.25"
            value={effort} onChange={(e) => setEffort(e.target.value)}
            className="w-28 bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
        </div>
      </div>
      {verdict === 'feasible_with_conditions' && (
        <div>
          <label htmlFor={`conditions-${departmentId}`} className="block text-xs text-slate-500 mb-1">
            {t('conditions')}
          </label>
          <input id={`conditions-${departmentId}`} type="text"
            value={conditions} onChange={(e) => setConditions(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
        </div>
      )}
      <textarea rows={2} placeholder="Notes" value={notes}
        onChange={(e) => setNotes(e.target.value)}
        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
      <button disabled={!ready || submit.isPending} onClick={() => submit.mutate()}
        className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm disabled:opacity-50">
        {t('assessment.submit')}
      </button>
    </div>
  )
}
