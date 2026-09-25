/**
 * Evidence and customer mails filed into one issue. Wraps the change's drop
 * zone; the upload carries `validation_issue_id` so the file lands in this
 * issue and nowhere else.
 */
import AttachmentDropzone from '../AttachmentDropzone'
import { AttachmentRow } from '../AttachmentRow'
import type { IssueOut } from '../../../types/validationIssue'
import { sectionLabel } from '../offer/offerFormat'

const Dropzone = AttachmentDropzone

export default function IssueDropzone({ changeId, issue, canAttach, onUploaded }: {
  changeId: number
  issue: IssueOut
  canAttach: boolean
  onUploaded: () => void
}) {
  const files = issue.attachments ?? []
  return (
    <div data-testid={`issue-files-${issue.id}`} className="space-y-1.5">
      <span className={sectionLabel}>Evidence and customer mails</span>
      {files.length > 0 ? (
        <ul className="divide-y divide-slate-800 text-xs">
          {files.map((a) => <AttachmentRow key={a.id} changeId={changeId} attachment={a} />)}
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
