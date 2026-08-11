/**
 * ChangeAttachments — upload zone plus two phase-split, individually-deletable
 * lists: the frozen scoping baseline and the documents added afterwards.
 *
 * Baseline documents (uploaded during capture/scoping) are the record a
 * decision was made on. Once the change leaves scoping they freeze — the
 * server rejects their deletion — so the UI hides their delete control too.
 * Later documents land in the "after scoping" list and stay editable.
 */
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { apiErrorMessage } from '../../lib/apiError'
import AttachmentDropzone from './AttachmentDropzone'
import { t } from '../../i18n/cmLabels'
import { UploadedBy } from '../common/UploadedBy'
import type { Attachment, ChangeDetail } from '../../types/change'

const isScopingPhase = (status: string) => status === 'captured' || status === 'scoping'

const KIND_LABEL: Record<string, string> = {
  info_request: 'attach.infoRequest',
  info_response: 'attach.infoResponse',
}

function KindChip({ kind }: { kind?: string | null }) {
  const key = kind ? KIND_LABEL[kind] : undefined
  if (!key) return null
  return (
    <span data-testid={`attach-kind-${kind}`}
      className={`inline-flex items-center rounded px-1 py-0 text-[10px] leading-tight font-medium ${
        kind === 'info_request'
          ? 'bg-amber-900/70 text-amber-200' : 'bg-emerald-900/70 text-emerald-200'}`}>
      {t(key)}
    </span>
  )
}

export default function ChangeAttachments({ change }: { change: ChangeDetail }) {
  const qc = useQueryClient()
  // Which open info request is currently collecting its answer.
  const [answering, setAnswering] = useState<number | null>(null)
  const invalidate = () => qc.invalidateQueries({ queryKey: ['change', change.id] })

  const del = async (a: Attachment) => {
    if (!window.confirm(`Delete "${a.filename}"?`)) return
    try {
      await changesApi.deleteAttachment(change.id, a.id)
      invalidate()
    } catch (e) {
      toast.error(apiErrorMessage(e, 'Could not delete attachment'))
    }
  }

  const baseline = change.attachments.filter((a) => a.phase !== 'post_scoping')
  const post = change.attachments.filter((a) => a.phase === 'post_scoping')
  // A response belongs under the question it answers, not adrift in the list.
  const responsesFor = (id: number) =>
    change.attachments.filter((a) => a.responds_to_id === id)
  const isResponse = (a: Attachment) => a.responds_to_id != null
  // Baseline docs are only deletable while the change is still in scoping.
  const baselineDeletable = isScopingPhase(change.status)

  const row = (a: Attachment, deletable: boolean) => (
    // Delete leads the row rather than trailing it: the control sits where the
    // eye starts, muted until the row is hovered so it never dominates the name.
    <li key={a.id} className="flex items-center gap-2 py-1 group">
      {deletable && (
        <button
          type="button"
          className="flex-shrink-0 text-slate-600 hover:text-red-400 opacity-40 group-hover:opacity-100 focus:opacity-100 transition-opacity"
          aria-label={`Delete ${a.filename}`}
          title="Delete attachment"
          onClick={() => del(a)}
        >
          ✕
        </button>
      )}
      <span className="min-w-0">
        <span className="block truncate">
          📎 {a.filename} <KindChip kind={a.kind} />
        </span>
        {/* Who put it there and when — the provenance every file list owes. */}
        <UploadedBy name={a.uploaded_by_name} at={a.created_at} className="block" />
      </span>
    </li>
  )

  // A question plus whatever came back, read as one block.
  const requestBlock = (a: Attachment, deletable: boolean) => {
    const answers = responsesFor(a.id)
    return (
      <li key={a.id} className="py-1">
        <ul className="divide-y divide-slate-700/40">
          {row(a, deletable)}
          {answers.length > 0 && (
            <ul className="ml-6 border-l border-slate-700 pl-3">
              {answers.map((r) => row(r, deletable))}
            </ul>
          )}
        </ul>
        {answers.length === 0 && (
          answering === a.id ? (
            <div className="ml-6 mt-1">
              <AttachmentDropzone changeId={change.id} kind="info_response"
                respondsToId={a.id} label={t('attach.responseSlot')}
                onUploaded={() => { setAnswering(null); invalidate() }} />
            </div>
          ) : (
            <button type="button" data-testid={`attach-response-${a.id}`}
              className="ml-6 text-xs text-sky-300 hover:text-sky-200"
              onClick={() => setAnswering(a.id)}>
              {t('attach.attachResponse')}
            </button>
          )
        )}
      </li>
    )
  }

  // Requests carry their answers; loose responses (question deleted) still show.
  const list = (items: Attachment[], deletable: boolean) =>
    items
      .filter((a) => !isResponse(a) || !items.some((q) => q.id === a.responds_to_id))
      .map((a) => (a.kind === 'info_request' ? requestBlock(a, deletable) : row(a, deletable)))

  return (
    <div className="pt-3 space-y-4">
      <div>
        <label className="text-sm text-slate-400 block mb-1">
          {t('attach.uploadLabel')}
        </label>
        <AttachmentDropzone changeId={change.id} onUploaded={invalidate} />
      </div>

      <div>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs uppercase tracking-wide text-slate-500">
            {t('attach.baseline')}
          </span>
          {!baselineDeletable && (
            <span className="text-xs text-slate-500" title={t('attach.frozenHint')}>
              🔒 {t('attach.frozen')}
            </span>
          )}
        </div>
        <ul className="text-sm divide-y divide-slate-700/60">
          {baseline.length === 0
            ? <li className="py-1 text-slate-500">{t('attach.none')}</li>
            : list(baseline, baselineDeletable)}
        </ul>
      </div>

      {(post.length > 0 || !isScopingPhase(change.status)) && (
        <div>
          <span className="text-xs uppercase tracking-wide text-slate-500 block mb-1">
            {t('attach.postScoping')}
          </span>
          <ul className="text-sm divide-y divide-slate-700/60">
            {post.length === 0
              ? <li className="py-1 text-slate-500">{t('attach.none')}</li>
              : list(post, true)}
          </ul>
        </div>
      )}
    </div>
  )
}
