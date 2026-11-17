/**
 * Christoph 2026-11-17: the change presentation a Yes owes can be a document
 * that is already on the change: the customer's initial request, or the deck
 * another department made first (shared with everyone after that). The slot
 * stays required; this is the "view and pick" next to the upload.
 */
import { useState } from 'react'
import { changesApi, type ReusableAttachment } from '../../api/changes'
import { API_BASE_URL } from '../../api/client'
import { t } from '../../i18n/cmLabels'
import { toastError } from '../../lib/apiError'

interface Props {
  changeId: number
  assessmentId: number
  caseRef?: string | null
  lang?: 'de' | 'en'
  onPicked: () => void
}

export default function ReuseDocumentPicker({ changeId, assessmentId, caseRef, lang = 'en', onPicked }: Props) {
  const [rows, setRows] = useState<ReusableAttachment[] | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)

  const load = () => changesApi.reusableAttachments(changeId, assessmentId, caseRef)
    .then(setRows).catch((e: unknown) => { setRows([]); toastError(e, t('reuse.loadFailed', lang)) })
  const toggle = () => { if (!open) void load(); setOpen(!open) }
  const pick = (a: ReusableAttachment) => {
    setBusy(a.id)
    changesApi.reuseAttachment(changeId, a.id, assessmentId, caseRef)
      .then(() => { setOpen(false); onPicked() })
      .catch((e: unknown) => toastError(e, t('reuse.failed', lang)))
      .finally(() => setBusy(null))
  }
  const tag = (a: ReusableAttachment) => (a.source === 'initial' ? t('reuse.initial', lang)
    : a.source === 'change_ppt'
      ? t('reuse.deck', lang).replace('{d}', a.department_name ?? a.uploaded_by_name ?? '')
      : t('reuse.other', lang))

  return (
    <div data-testid="reuse-picker" className="text-xs">
      <button type="button" onClick={toggle} aria-expanded={open} data-testid="reuse-toggle"
        className="text-sky-300 hover:text-sky-200 underline underline-offset-2">
        {t('reuse.toggle', lang)}
      </button>
      {open && (
        <div className="mt-1 rounded border border-slate-700 bg-slate-900/60 p-1.5">
          {rows === null && <p className="text-slate-400">{t('reuse.loading', lang)}</p>}
          {rows !== null && rows.length === 0 && (
            <p className="text-slate-400" data-testid="reuse-empty">{t('reuse.empty', lang)}</p>
          )}
          {rows !== null && rows.length > 0 && (
            <ul className="space-y-1">
              {rows.map((a) => (
                <li key={a.id} data-testid={`reuse-row-${a.id}`} className="flex flex-wrap items-center gap-2">
                  <a href={`${API_BASE_URL}/v1/changes/${changeId}/attachments/${a.id}/download`}
                    download={a.filename} title={t('reuse.view', lang)}
                    className="min-w-0 flex-1 truncate text-sky-300 hover:text-sky-200">{a.filename}</a>
                  <span className={`rounded px-1.5 text-[11px] ${a.source === 'initial'
                    ? 'bg-emerald-900/60 text-emerald-200' : a.source === 'change_ppt'
                      ? 'bg-sky-900/70 text-sky-200' : 'bg-slate-700 text-slate-200'}`}>{tag(a)}</span>
                  <button type="button" disabled={busy !== null} onClick={() => pick(a)}
                    data-testid={`reuse-pick-${a.id}`}
                    className="rounded bg-sky-800 px-2 py-0.5 text-white hover:bg-sky-700 disabled:opacity-50">
                    {t('reuse.use', lang)}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
