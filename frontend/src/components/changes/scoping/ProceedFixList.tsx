/**
 * The proceed dialog's body (C33, spec §3 "Proceed dialog"): what is still
 * in the way, fixable in place.
 *
 * - Questions (they hold proceed, HARD #2) as a fix list: per row "Answer
 *   now" (the answer form) and, for the asker or Project Management, "Make it
 *   a check item" when the scope can be decided without it.
 * - Check items collapsed by owner: they go along as the conditions of the
 *   go, each due with its department's assessment; "Promote to question".
 * - A department that owns check items but is not routed: "Route <dept>:
 *   C / R" (C preselected for Process and Quality), written to the meeting's
 *   RASIC call.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { btnSm } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'
import { changesApi } from '../../../api/changes'
import { t } from '../../../i18n/cmLabels'
import AnswerForm from './AnswerForm'
import { CheckRow } from './ScopingFlags'
import {
  isCheckItem, type Attachment, type ChangeConcern, type ChangeMeeting, type RasicLetter,
} from '../../../types/change'

/** C is the default for these (spec §3 "Not routed"). */
const CONSULTED_FIRST = ['Process Engineer', 'Quality']

export default function ProceedFixList({
  changeId, meeting, concerns, attachments, departments, confirmerName, onChanged,
}: {
  changeId: number
  meeting: ChangeMeeting
  concerns: ChangeConcern[]
  attachments: Attachment[]
  departments: { id: number; name: string }[]
  confirmerName?: string | null
  onChanged: () => void
}) {
  const [answering, setAnswering] = useState<number | null>(null)
  const open = concerns.filter((c) => c.is_open && c.kind !== 'risk')
  const questions = open.filter((c) => !isCheckItem(c)).sort((a, b) => a.id - b.id)
  const checks = open.filter(isCheckItem).sort((a, b) => a.id - b.id)
  const routed = new Set(Object.keys(meeting.department_rasic ?? {}).map(Number))
  if (!meeting.department_rasic) meeting.selected_department_ids.forEach((id) => routed.add(id))
  // Owners of check items the meeting has not routed.
  const unrouted = new Map<number, number>()
  for (const c of checks) {
    for (const id of [c.department_id, ...(c.co_department_ids ?? [])]) {
      if (id != null && !routed.has(id)) unrouted.set(id, (unrouted.get(id) ?? 0) + 1)
    }
  }
  const nameOf = (id: number) => departments.find((d) => d.id === id)?.name ?? `#${id}`

  const makeCheck = useMutation({
    mutationFn: (id: number) => changesApi.setConcernType(changeId, id, { flag_type: 'check' }),
    onSuccess: onChanged,
    onError: (e: unknown) => { toastError(e, 'Could not make it a check item') },
  })
  const route = useMutation({
    mutationFn: (vars: { id: number; letter: RasicLetter }) =>
      changesApi.updateMeeting(changeId, meeting.id, {
        department_rasic: { ...(meeting.department_rasic ?? Object.fromEntries(
          meeting.selected_department_ids.map((d) => [d, 'R']))), [vars.id]: vars.letter },
      }),
    onSuccess: onChanged,
    onError: (e: unknown) => { toastError(e, 'Could not route the department') },
  })

  return (
    <div className="space-y-3 text-sm" data-testid="proceed-fix-list">
      {questions.length > 0 && (
        <section className="space-y-1.5" data-testid="proceed-questions">
          <p className="text-xs text-amber-200">{t('proceed.questionsOpen')}</p>
          <ul className="space-y-1.5">
            {questions.map((c) => (
              <li key={c.id} className="rounded border border-amber-800/60 bg-amber-950/20 p-2 space-y-1"
                data-testid={`proceed-question-${c.id}`}>
                <p className="text-xs text-slate-100">
                  <span className="font-semibold">{c.asking_department_name ?? c.raised_by_name}:</span>{' '}
                  {c.note}
                </p>
                <div className="flex flex-wrap gap-3 text-xs">
                  {c.can_answer && answering !== c.id && (
                    <button type="button" className="text-sky-300 hover:text-sky-200"
                      data-testid={`proceed-answer-${c.id}`} onClick={() => setAnswering(c.id)}>
                      {t('proceed.answerNow')}
                    </button>
                  )}
                  {c.can_switch && (
                    <button type="button" className="text-sky-300 hover:text-sky-200"
                      data-testid={`proceed-make-check-${c.id}`} disabled={makeCheck.isPending}
                      onClick={() => makeCheck.mutate(c.id)}>
                      {t('flag.makeCheck')}
                    </button>
                  )}
                </div>
                {answering === c.id && (
                  <AnswerForm changeId={changeId} concern={c} attachments={attachments}
                    confirmerName={confirmerName}
                    onDone={() => { setAnswering(null); onChanged() }} />
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {[...unrouted.entries()].map(([id, n]) => {
        const name = nameOf(id)
        const letters: RasicLetter[] = CONSULTED_FIRST.includes(name) ? ['C', 'R'] : ['R', 'C']
        return (
          <div key={id} className="flex flex-wrap items-center gap-2 text-xs"
            data-testid={`proceed-unrouted-${id}`}>
            <span className="text-slate-300">
              {t('proceed.notRouted').replace('{d}', name).replace('{n}', String(n))}
            </span>
            {letters.map((l, i) => (
              <button key={l} type="button" disabled={route.isPending}
                data-testid={`proceed-route-${id}-${l}`}
                className={i === 0 ? btnSm.primary : btnSm.secondary}
                onClick={() => route.mutate({ id, letter: l })}>
                {t('proceed.routeAs').replace('{d}', name).replace('{l}', l)}
              </button>
            ))}
          </div>
        )
      })}

      {checks.length > 0 && (
        <details className="rounded border border-slate-700" data-testid="proceed-checks">
          <summary className="cursor-pointer px-2 py-1 text-xs text-slate-300">
            {t('proceed.checksByOwner')} ({checks.length})
          </summary>
          <ul className="divide-y divide-slate-700/60">
            {checks.map((c) => (
              <CheckRow key={c.id} changeId={changeId} c={c} editable onChanged={onChanged} />
            ))}
          </ul>
        </details>
      )}
      {checks.length > 0 && (
        <p className="text-[11px] text-slate-400">{t('proceed.conditionsInfo')}</p>
      )}
    </div>
  )
}
