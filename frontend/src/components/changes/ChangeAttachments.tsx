/**
 * ChangeAttachments — upload zone plus two phase-split, individually-deletable
 * lists: the frozen scoping baseline and the documents added afterwards.
 *
 * Baseline documents (uploaded during capture/scoping) are the record a
 * decision was made on. Once the change leaves scoping they freeze — the
 * server rejects their deletion — so the UI hides their delete control too.
 * Later documents land in the "after scoping" list and stay editable.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useDepartments } from '../../hooks/queries/useWorkflows'
import { toast } from 'sonner'
import { changesApi } from '../../api/changes'
import { apiErrorMessage } from '../../lib/apiError'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow, InfoRequestBlock, attachmentBlocks } from './AttachmentRow'
import { Lock } from 'lucide-react'
import { t } from '../../i18n/cmLabels'
import type { Attachment, ChangeDetail } from '../../types/change'

const isScopingPhase = (status: string) => status === 'captured' || status === 'scoping'

export default function ChangeAttachments({ change, readOnly = false, mayDelete = () => true }: {
  change: ChangeDetail
  /** Closed or canceled: documents are a record, nothing is added or deleted. */
  readOnly?: boolean
  /** Who may remove this document (the server's rule): no Delete for the rest. */
  mayDelete?: (a: Attachment) => boolean
}) {
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

  // Christoph 2026-11-09: every later file says which department it is from
  // and what it is for (case, supplier quote of which line, answer to what)
  const { data: depts = [] } = useDepartments()
  const { data: positions = [] } = useQuery({
    queryKey: ['costing-positions', change.id],
    queryFn: () => changesApi.listCostPositions(change.id),
  })
  const { data: concerns = [] } = useQuery({
    queryKey: ['change', change.id, 'concerns'],
    queryFn: () => changesApi.listConcerns(change.id),
  })
  const deptName = (id?: number | null) =>
    (depts as { id: number; name: string }[]).find((d) => d.id === id)?.name ?? null
  const caseText = (ref: string): string | null => {
    for (const a of change.assessments ?? []) {
      let det: Record<string, unknown> = {}
      try { det = typeof a.details === 'string' ? JSON.parse(a.details) : (a.details ?? {}) } catch { det = {} }
      for (const i of (det.impacts as { cases?: (string | { id: string; text: string })[] }[] | undefined) ?? []) {
        for (const c of i.cases ?? []) if (typeof c !== 'string' && c.id === ref) return c.text
      }
    }
    return null
  }
  const plain = (l: string) => l.replace(/^Spare part: /, '')
  const originOf = (a: Attachment): { department?: string | null; what?: string | null } | undefined => {
    if (a.costing_offer_id != null) {
      for (const p of positions) {
        const o = (p.offers ?? []).find((x) => x.id === a.costing_offer_id)
        if (o) {
          const spare = /spare part/i.test(`${p.notes ?? ''} ${p.label}`)
          return { department: deptName(p.department_id),
            what: `Costing: ${o.vendor_name} quote for ${spare ? 'spare part ' : ''}"${plain(p.label)}"` }
        }
      }
      return { what: 'Costing: supplier quote' }
    }
    const asm = (change.assessments ?? []).find((x) => x.id === a.assessment_id)
    const dep = asm ? deptName(asm.department_id) : null
    if (a.case_ref) {
      const txt = caseText(a.case_ref)
      return { department: dep, what: `Assessment${txt ? `, case "${txt}"` : ''}` }
    }
    if (asm) return { department: dep, what: 'Assessment evidence' }
    if (a.concern_id != null) {
      const c = (concerns as { id: number; note: string; asking_department_name?: string | null;
        department_id?: number | null }[]).find((x) => x.id === a.concern_id)
      const q = c ? `"${c.note.slice(0, 60)}${c.note.length > 60 ? '…' : ''}"` : ''
      return { department: c?.asking_department_name ?? deptName(c?.department_id),
        what: a.kind === 'info_response' ? `Answer to the question ${q}` : `Question ${q}` }
    }
    if (a.kind === 'info_response') return { what: 'Answer to a question' }
    if (a.kind === 'info_request') return { what: 'Question asked' }
    return undefined
  }

  const baseline = change.attachments.filter((a) => a.phase !== 'post_scoping')
  const post = change.attachments.filter((a) => a.phase === 'post_scoping')
  // Baseline docs are only deletable while the change is still in scoping.
  const baselineDeletable = !readOnly && isScopingPhase(change.status)

  // One renderer for every row; requests carry their answers with them.
  const list = (items: Attachment[], deletable: boolean) =>
    attachmentBlocks(items).map((b) =>
      b.request ? (
        <InfoRequestBlock key={b.request.id} changeId={change.id} request={b.request}
          responses={b.responses} onChanged={invalidate}
          onDelete={deletable && mayDelete(b.request) ? del : undefined} />
      ) : (
        <AttachmentRow key={b.plain!.id} changeId={change.id} attachment={b.plain!}
          origin={originOf(b.plain!)}
          onDelete={deletable && mayDelete(b.plain!) ? del : undefined} />
      ))

  return (
    <div className="pt-3 space-y-4">
      {/* §2: a customer change is complete with the customer's own file */}
      {!readOnly && change.customer_relevant && change.scoping_v2 && (
        <div data-testid="customer-file-zone">
          <p className="text-sm text-slate-400 mb-1">{t('attach.customerFile')}</p>
          <AttachmentDropzone changeId={change.id} kind="customer_file" onUploaded={invalidate} />
        </div>
      )}
      {!readOnly && (
        <div>
          <p className="text-sm text-slate-400 mb-1">{t('attach.uploadLabel')}</p>
          <AttachmentDropzone changeId={change.id} onUploaded={invalidate} />
        </div>
      )}

      <div>
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs uppercase tracking-wide text-slate-500">
            {t('attach.baseline')}
          </span>
          {!baselineDeletable && (
            <span className="inline-flex items-center gap-1 text-xs text-slate-400" title={t('attach.frozenHint')}>
              <Lock aria-hidden="true" size={11} />{t('attach.frozen')}
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
              : list(post, !readOnly)}
          </ul>
        </div>
      )}
    </div>
  )
}
