import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { useDepartments } from '../../hooks/queries/useWorkflows'
import { t } from '../../i18n/cmLabels'
import type { ChangeStatus, ChangeMeeting } from '../../types/change'

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

const DECISION_LABEL: Record<string, string> = {
  proceed: t('meeting.proceed'), reject: t('meeting.reject'),
  needs_info: t('meeting.needsInfo'),
}

export default function ScopingPanel({ changeId, status }: {
  changeId: number; status: ChangeStatus
}) {
  const qc = useQueryClient()
  const { data: meetings = [] } = useQuery({
    queryKey: ['change-meetings', changeId],
    queryFn: () => changesApi.listMeetings(changeId),
  })
  const { data: departments = [] } = useDepartments()

  const [date, setDate] = useState('')
  const [participants, setParticipants] = useState('')
  const [notes, setNotes] = useState('')
  const [deptIds, setDeptIds] = useState<number[]>([])

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['change-meetings', changeId] })
    qc.invalidateQueries({ queryKey: ['change', changeId] })
  }
  const create = useMutation({
    mutationFn: () => changesApi.createMeeting(changeId, {
      meeting_date: date ? `${date}T12:00:00Z` : undefined,
      participants: participants.split(',').map((n) => n.trim())
        .filter(Boolean).map((name) => ({ name })),
      notes: notes || undefined,
      selected_department_ids: deptIds,
    }),
    onSuccess: () => { setNotes(''); setParticipants(''); invalidate() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not record the meeting'),
  })
  const decide = useMutation({
    mutationFn: (vars: { meetingId: number; decision: 'proceed' | 'reject' | 'needs_info' }) =>
      changesApi.decideMeeting(changeId, vars.meetingId, vars.decision),
    onSuccess: invalidate,
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Decision failed'),
  })

  const open = status === 'captured' || status === 'scoping'
  const toggleDept = (id: number) => setDeptIds((prev) =>
    prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id])

  return (
    <div className="space-y-4 text-sm">
      <ul className="divide-y divide-slate-700 border border-slate-700 rounded-lg">
        {meetings.map((m: ChangeMeeting) => (
          <li key={m.id} className="p-3 space-y-1">
            <div className="flex justify-between items-center">
              <span className="text-slate-200">
                {new Date(m.meeting_date).toLocaleDateString()} — {' '}
                {m.participants.map((p) => p.name).join(', ') || '—'}
              </span>
              {m.decision ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-700 text-slate-200">
                  {DECISION_LABEL[m.decision] ?? m.decision}
                </span>
              ) : open && (
                <span className="flex gap-2">
                  <button className="bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-xs"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ meetingId: m.id, decision: 'proceed' })}>
                    {t('meeting.proceed')}
                  </button>
                  <button className="bg-amber-700 hover:bg-amber-600 text-white px-2.5 py-1 rounded text-xs"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ meetingId: m.id, decision: 'needs_info' })}>
                    {t('meeting.needsInfo')}
                  </button>
                  <button className="bg-red-800 hover:bg-red-700 text-white px-2.5 py-1 rounded text-xs"
                    disabled={decide.isPending}
                    onClick={() => decide.mutate({ meetingId: m.id, decision: 'reject' })}>
                    {t('meeting.reject')}
                  </button>
                </span>
              )}
            </div>
            {m.notes && <p className="text-slate-400 whitespace-pre-wrap">{m.notes}</p>}
            {m.selected_department_ids.length > 0 && (
              <p className="text-xs text-slate-500">
                {t('meeting.departments')}: {m.selected_department_ids.map((id) =>
                  departments.find((d) => d.id === id)?.name ?? `#${id}`).join(', ')}
              </p>
            )}
          </li>
        ))}
        {meetings.length === 0 && (
          <li className="p-3 text-slate-400">{t('meeting.none')}</li>
        )}
      </ul>

      {open && (
        <div className="border border-slate-700 rounded-lg p-4 space-y-3">
          <h3 className="text-xs uppercase tracking-wide text-slate-500">{t('scoping.newMeeting')}</h3>
          <div className="flex flex-wrap gap-3">
            <div>
              <label className="block text-xs text-slate-500 mb-1">{t('meeting.date')}</label>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)}
                className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
            </div>
            <div className="flex-1 min-w-[14rem]">
              <label className="block text-xs text-slate-500 mb-1">
                {t('meeting.participants')} <span className="opacity-60">({t('meeting.participantsHint')})</span>
              </label>
              <input type="text" value={participants} onChange={(e) => setParticipants(e.target.value)}
                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">{t('meeting.notes')}</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={4}
              className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">{t('meeting.departments')}</label>
            <div className="flex flex-wrap gap-2">
              {departments.map((d) => (
                <button key={d.id} type="button" onClick={() => toggleDept(d.id)}
                  className={`px-2.5 py-1 rounded-full text-xs border ${deptIds.includes(d.id)
                    ? 'bg-sky-600 text-white border-sky-500'
                    : 'bg-slate-900 text-slate-300 border-slate-600'}`}>
                  {d.name}
                </button>
              ))}
            </div>
          </div>
          <button
            className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm disabled:opacity-50"
            disabled={create.isPending}
            onClick={() => create.mutate()}>
            {t('scoping.newMeeting')}
          </button>
        </div>
      )}
    </div>
  )
}
