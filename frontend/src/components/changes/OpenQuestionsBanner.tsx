import { CircleAlert } from 'lucide-react';
import { t } from '../../i18n/cmLabels';
import type { ChangeConcern } from '../../types/change';

/**
 * Open scoping questions hold the change (Christoph 2026-10-28: "a warning
 * that everyone sees the impact"). Shown above the tabs on every tab, to
 * every viewer, while the change is captured or in scoping: how many
 * questions are open, that the change does not move on until they are
 * answered and closed, and per question who answers it.
 */
export default function OpenQuestionsBanner({ status, concerns, onShow }: {
  status: string
  concerns: ChangeConcern[]
  onShow?: () => void
}) {
  if (status !== 'captured' && status !== 'scoping') return null
  const open = concerns
    .filter((c) => c.is_open && c.kind === 'needs_info' && c.flag_type !== 'check')
    .sort((a, b) => a.id - b.id)
  if (open.length === 0) return null
  return (
    <div role="alert" data-testid="open-questions-banner"
      className="mt-3 rounded-lg border border-amber-700/60 bg-amber-950/40 px-4 py-3 text-sm">
      <p className="flex items-center gap-2 font-semibold text-amber-200">
        <CircleAlert aria-hidden="true" size={16} className="shrink-0" />
        {t(open.length === 1 ? 'openQ.title1' : 'openQ.titleN').replace('{n}', String(open.length))}
      </p>
      <p className="mt-1 text-amber-100/80">{t('openQ.impact')}</p>
      <ul className="mt-2 space-y-0.5 text-amber-100/90">
        {open.map((c) => (
          <li key={c.id} data-testid={`open-question-${c.id}`}>
            <span className="text-amber-300/80">
              {c.answered_at
                ? t('openQ.answered')
                : c.answer_from ? t(`flag.from.${c.answer_from}`)
                  : c.asking_department_name ?? t('openQ.noOwner')}:
            </span>{' '}
            {c.note}
          </li>
        ))}
      </ul>
      {onShow && (
        <button type="button" data-testid="open-questions-show" onClick={onShow}
          className="mt-2 text-xs font-medium text-amber-200 underline underline-offset-2 hover:text-amber-100">
          {t('openQ.show')}
        </button>
      )}
    </div>
  );
}
