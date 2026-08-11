/**
 * The one way a change attachment is drawn — filename as a download link, its
 * place in the needs-info loop, and who put it there. Shared by the attachments
 * list and the scoping panel's needs-info block so Sales sees the same row
 * wherever they meet it.
 */
import { useState } from 'react'
import { API_BASE_URL } from '../../api/client'
import AttachmentDropzone from './AttachmentDropzone'
import { UploadedBy } from '../common/UploadedBy'
import { t } from '../../i18n/cmLabels'
import type { Attachment } from '../../types/change'

const KIND_LABEL: Record<string, string> = {
  info_request: 'attach.infoRequest',
  info_response: 'attach.infoResponse',
  rejection_letter: 'attach.rejectionLetter',
  rfq: 'attach.rfq',
}

const KIND_STYLE: Record<string, string> = {
  info_request: 'bg-amber-900/70 text-amber-200',
  info_response: 'bg-emerald-900/70 text-emerald-200',
  rejection_letter: 'bg-red-900/70 text-red-200',
  rfq: 'bg-violet-900/70 text-violet-200',
}

export function KindChip({ kind }: { kind?: string | null }) {
  const key = kind ? KIND_LABEL[kind] : undefined
  if (!key) return null
  return (
    <span data-testid={`attach-kind-${kind}`}
      className={`inline-flex items-center rounded px-1 py-0 text-[10px] leading-tight font-medium ${
        KIND_STYLE[kind!] ?? 'bg-slate-700 text-slate-200'}`}>
      {t(key)}
    </span>
  )
}

export function AttachmentRow({ changeId, attachment: a, onDelete }: {
  changeId: number
  attachment: Attachment
  /** Omitted where the file may not be deleted (frozen baseline, read-only view). */
  onDelete?: (a: Attachment) => void
}) {
  return (
    // Delete leads the row rather than trailing it: the control sits where the
    // eye starts, muted until the row is hovered so it never dominates the name.
    <li className="flex items-center gap-2 py-1 group">
      {onDelete && (
        <button
          type="button"
          className="flex-shrink-0 text-slate-600 hover:text-red-400 opacity-40 group-hover:opacity-100 focus:opacity-100 transition-opacity"
          aria-label={`Delete ${a.filename}`}
          title="Delete attachment"
          onClick={() => onDelete(a)}
        >
          ✕
        </button>
      )}
      <span className="min-w-0">
        <span className="block truncate">
          📎{' '}
          <a href={`${API_BASE_URL}/v1/changes/${changeId}/attachments/${a.id}/download`}
            download={a.filename}
            className="text-sky-300 hover:text-sky-200 hover:underline">
            {a.filename}
          </a>{' '}
          <KindChip kind={a.kind} />
        </span>
        {/* Who put it there and when — the provenance every file list owes. */}
        <UploadedBy name={a.uploaded_by_name} at={a.created_at} className="block" />
      </span>
    </li>
  )
}

/**
 * A question to the customer with whatever came back under it, and — while it is
 * still unanswered — the slot that files the answer against this very request.
 */
export function InfoRequestBlock({ changeId, request, responses, onChanged, onDelete }: {
  changeId: number
  request: Attachment
  responses: Attachment[]
  onChanged: () => void
  onDelete?: (a: Attachment) => void
}) {
  const [answering, setAnswering] = useState(false)
  return (
    <li className="py-1">
      <ul className="divide-y divide-slate-700/40">
        <AttachmentRow changeId={changeId} attachment={request} onDelete={onDelete} />
        {responses.length > 0 && (
          <ul className="ml-6 border-l border-slate-700 pl-3">
            {responses.map((r) => (
              <AttachmentRow key={r.id} changeId={changeId} attachment={r} onDelete={onDelete} />
            ))}
          </ul>
        )}
      </ul>
      {responses.length === 0 && (
        answering ? (
          <div className="ml-6 mt-1">
            {/* Inherit the question's container, so an answer filed from the
                attachments list lands in the same card as its question. */}
            <AttachmentDropzone changeId={changeId} kind="info_response"
              respondsToId={request.id} concernId={request.concern_id ?? undefined}
              label={t('attach.responseSlot')}
              onUploaded={() => { setAnswering(false); onChanged() }} />
          </div>
        ) : (
          <button type="button" data-testid={`attach-response-${request.id}`}
            className="ml-6 text-xs text-sky-300 hover:text-sky-200"
            onClick={() => setAnswering(true)}>
            {t('attach.attachResponse')}
          </button>
        )
      )}
    </li>
  )
}

/** Requests first with their answers nested; a response whose request is absent
 *  still shows, so nothing can go missing from a list. */
export function attachmentBlocks(items: Attachment[]): {
  request: Attachment | null; responses: Attachment[]; plain: Attachment | null
}[] {
  return items
    .filter((a) => a.responds_to_id == null || !items.some((q) => q.id === a.responds_to_id))
    .map((a) => a.kind === 'info_request'
      ? { request: a, responses: items.filter((r) => r.responds_to_id === a.id), plain: null }
      : { request: null, responses: [], plain: a })
}
