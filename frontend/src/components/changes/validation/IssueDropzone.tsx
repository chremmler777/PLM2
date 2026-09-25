/**
 * Evidence and customer mails filed into one issue. Wraps the change's drop
 * zone; the upload carries `validation_issue_id` so the file lands in this
 * issue and nowhere else. A file can be removed by whoever the backend says
 * may (`can_delete`); without that word, by its uploader, PM, the lead or an
 * admin while the issue is open. The server still decides: a refusal (a
 * customer mail an accepted concession stands on) comes back as a toast.
 */
import { useMutation } from '@tanstack/react-query'
import { toast } from 'sonner'
import AttachmentDropzone from '../AttachmentDropzone'
import { AttachmentRow } from '../AttachmentRow'
import { changesApi } from '../../../api/changes'
import type { IssueOut } from '../../../types/validationIssue'
import { isIssueOpen } from '../../../types/validationIssue'
import { sectionLabel } from '../offer/offerFormat'
import type { IssueViewer } from './issueModel'
import { errDetail } from './useIssueMutation'

const Dropzone = AttachmentDropzone

type IssueFile = IssueOut['attachments'][number]

/** May the viewer remove this file? The backend's `can_delete` wins when sent. */
export const mayDeleteIssueFile = (issue: IssueOut, a: IssueFile, v: IssueViewer = {}): boolean =>
  a.can_delete ?? (isIssueOpen(issue)
    && (!!v.isAdmin || !!v.canManage || (v.id != null && a.uploaded_by === v.id)))

export default function IssueDropzone({ changeId, issue, canAttach, onUploaded, viewer }: {
  changeId: number
  issue: IssueOut
  canAttach: boolean
  onUploaded: () => void
  viewer?: IssueViewer
}) {
  const files = issue.attachments ?? []
  const remove = useMutation({
    mutationFn: (id: number) => changesApi.deleteAttachment(changeId, id),
    onSuccess: () => { toast.success('File removed'); onUploaded() },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Could not remove the file'),
  })
  return (
    <div data-testid={`issue-files-${issue.id}`} className="space-y-1.5">
      <span className={sectionLabel}>Evidence and customer mails</span>
      {files.length > 0 ? (
        <ul className="divide-y divide-slate-800 text-xs">
          {files.map((a) => (
            <AttachmentRow key={a.id} changeId={changeId} attachment={a}
              onDelete={mayDeleteIssueFile(issue, a, viewer) && !remove.isPending
                ? () => { if (window.confirm(`Remove ${a.filename} from this issue?`)) remove.mutate(a.id) }
                : undefined} />
          ))}
        </ul>
      ) : (
        <p className="text-xs text-slate-500">
          Nothing filed yet. Drop photos, measurement reports or the customer's mail (.msg, .eml) here.
        </p>
      )}
      {canAttach && (
        <div className="grid gap-2 sm:grid-cols-2">
          <Dropzone changeId={changeId} validationIssueId={issue.id} compact
            label="Drop evidence" onUploaded={onUploaded} />
          <Dropzone changeId={changeId} validationIssueId={issue.id} compact kind="customer_email"
            label="Drop customer mail" onUploaded={onUploaded} />
        </div>
      )}
    </div>
  )
}
