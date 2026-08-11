/**
 * ChangeAttachments — upload zone plus two phase-split, individually-deletable
 * lists: the frozen scoping baseline and the documents added afterwards.
 *
 * Baseline documents (uploaded during capture/scoping) are the record a
 * decision was made on. Once the change leaves scoping they freeze — the
 * server rejects their deletion — so the UI hides their delete control too.
 * Later documents land in the "after scoping" list and stay editable.
 */
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { apiErrorMessage } from '../../lib/apiError'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow, InfoRequestBlock, attachmentBlocks } from './AttachmentRow'
import { t } from '../../i18n/cmLabels'
import type { Attachment, ChangeDetail } from '../../types/change'

const isScopingPhase = (status: string) => status === 'captured' || status === 'scoping'

export default function ChangeAttachments({ change }: { change: ChangeDetail }) {
  const qc = useQueryClient()
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
  // Baseline docs are only deletable while the change is still in scoping.
  const baselineDeletable = isScopingPhase(change.status)

  // One renderer for every row; requests carry their answers with them.
  const list = (items: Attachment[], deletable: boolean) =>
    attachmentBlocks(items).map((b) =>
      b.request ? (
        <InfoRequestBlock key={b.request.id} changeId={change.id} request={b.request}
          responses={b.responses} onChanged={invalidate}
          onDelete={deletable ? del : undefined} />
      ) : (
        <AttachmentRow key={b.plain!.id} changeId={change.id} attachment={b.plain!}
          onDelete={deletable ? del : undefined} />
      ))

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
