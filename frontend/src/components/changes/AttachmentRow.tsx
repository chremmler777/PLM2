/**
 * The one way a change attachment is drawn — filename as a download link, its
 * place in the needs-info loop, and who put it there. Shared by the attachments
 * list and the scoping panel's needs-info block so Sales sees the same row
 * wherever they meet it.
 */
import { useState } from 'react'
import { Download, Paperclip, X } from 'lucide-react'
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
  change_ppt: 'bucket.changePpt',
  customer_email: 'attach.customerEmail',
  vendor_quote: 'attach.vendorQuote',
  customer_file: 'attach.customerFileChip',
}

const KIND_STYLE: Record<string, string> = {
  info_request: 'bg-amber-900/70 text-amber-200',
  info_response: 'bg-emerald-900/70 text-emerald-200',
  rejection_letter: 'bg-red-900/70 text-red-200',
  rfq: 'bg-violet-900/70 text-violet-200',
  change_ppt: 'bg-sky-900/70 text-sky-200',
  customer_email: 'bg-teal-900/70 text-teal-200',
  vendor_quote: 'bg-slate-700 text-slate-100',
  customer_file: 'bg-teal-900/70 text-teal-200',
}

export function KindChip({ kind }: { kind?: string | null }) {
  const key = kind ? KIND_LABEL[kind] : undefined
  if (!key) return null
  return (
    <span data-testid={`attach-kind-${kind}`}
      className={`inline-flex items-center rounded px-1 py-px text-[11px] leading-tight font-medium ${
        KIND_STYLE[kind!] ?? 'bg-slate-700 text-slate-200'}`}>
      {t(key)}
    </span>
  )
}

export function AttachmentRow({ changeId, attachment: a, onDelete, confirm = false, tag, origin }: {
  changeId: number
  attachment: Attachment
  /** Omitted where the file may not be deleted (frozen baseline, read-only view). */
  onDelete?: (a: Attachment) => void
  /** Ask "Delete? Yes / No" before deleting (Christoph 2026-11-08). */
  confirm?: boolean
  /** What the file belongs to, as a chip (e.g. "Case 1 · Re-cut insert LH"). */
  tag?: string
  /** Christoph 2026-11-09: where the file comes from (department · what it is for). */
  origin?: { department?: string | null; what?: string | null }
}) {
  const [asking, setAsking] = useState(false)
  return (
    // Delete leads the row rather than trailing it: the control sits where the
    // eye starts, muted until the row is hovered so it never dominates the name.
    <li className="flex items-center gap-2 py-1 group">
      {onDelete && (
        <button
          type="button"
          className="flex-shrink-0 rounded text-slate-500 hover:text-red-400 opacity-60 group-hover:opacity-100 focus:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 transition-opacity"
          aria-label={`Delete ${a.filename}`}
          title="Delete attachment"
          onClick={() => (confirm ? setAsking(true) : onDelete(a))}
        >
          <X aria-hidden="true" size={14} />
        </button>
      )}
      {onDelete && asking && (
        <span className="inline-flex items-center gap-1 flex-shrink-0" data-testid={`attach-confirm-${a.id}`}>
          <span className="text-[11px] text-red-200">{t('risk.confirmDelete')}</span>
          <button type="button" data-testid={`attach-delete-yes-${a.id}`}
            className="rounded bg-red-800 px-1.5 text-[11px] text-white hover:bg-red-700"
            onClick={() => { setAsking(false); onDelete(a) }}>{t('risk.yes')}</button>
          <button type="button" className="rounded border border-slate-600 px-1.5 text-[11px] text-slate-200"
            onClick={() => setAsking(false)}>{t('risk.no')}</button>
        </span>
      )}
      <span className="min-w-0">
        <span className="block truncate">
          <Paperclip aria-hidden="true" size={12} className="mr-1 inline align-[-1px] text-slate-500" />
          <a href={`${API_BASE_URL}/v1/changes/${changeId}/attachments/${a.id}/download`}
            download={a.filename}
            className="text-sky-300 hover:text-sky-200 hover:underline">
            {a.filename}
          </a>{' '}
          <KindChip kind={a.kind} />
          {tag && (
            <span data-testid={`attach-tag-${a.id}`}
              className="ml-1 inline-flex items-center rounded bg-amber-900/60 px-1 py-px text-[11px] leading-tight font-medium text-amber-100">
              {tag}
            </span>
          )}
        </span>
        {origin && (origin.department || origin.what) && (
          <span data-testid={`attach-origin-${a.id}`} className="block text-xs text-slate-300">
            {origin.department && (
              <span className="mr-1.5 inline-flex items-center rounded border border-slate-600 px-1 py-px text-[11px] font-medium text-slate-100">
                {origin.department}</span>
            )}
            {origin.what}
          </span>
        )}
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


/** Christoph 2026-11-08: a question's files as inline download icons. */
export function DownloadIcons({ changeId, attachments }: { changeId: number; attachments: Attachment[] }) {
  if (!attachments.length) return null
  return (
    <span className="inline-flex items-center gap-1 ml-1" data-testid="download-icons">
      {attachments.map((a) => (
        <a key={a.id} href={`${API_BASE_URL}/v1/changes/${changeId}/attachments/${a.id}/download`}
          download={a.filename} title={a.filename} aria-label={`Download ${a.filename}`}
          className="inline-flex items-center gap-0.5 rounded px-1 text-sky-300 hover:text-sky-200 hover:bg-slate-700/60">
          <Download aria-hidden="true" size={12} />
          <span className="max-w-[10rem] truncate text-[11px]">{a.filename}</span>
        </a>
      ))}
    </span>
  )
}
