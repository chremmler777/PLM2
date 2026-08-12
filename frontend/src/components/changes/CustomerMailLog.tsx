/**
 * What the customer actually said, on the change itself.
 *
 * Customer correspondence lives in mailboxes nobody else can search, so the
 * change record ends up quoting mails that only one person has. This card is the
 * shared copy: saved mails (.msg/.eml, or a PDF printout) in the order they
 * happened, uploadable by anyone who opens the change — there is no point
 * restricting it, since the person holding the mail is rarely the change lead.
 *
 * Nothing is parsed: the file is the record.
 */
import { useQueryClient } from '@tanstack/react-query'
import AttachmentDropzone from './AttachmentDropzone'
import { AttachmentRow } from './AttachmentRow'
import { t } from '../../i18n/cmLabels'
import type { Attachment } from '../../types/change'

export default function CustomerMailLog({ changeId, attachments }: {
  changeId: number
  /** The change's documents; the card picks its own out of them. */
  attachments: Attachment[]
}) {
  const qc = useQueryClient()
  // Oldest first: a mail thread reads forward, not backward.
  const mails = attachments
    .filter((a) => a.kind === 'customer_email')
    .sort((a, b) => a.created_at.localeCompare(b.created_at))

  return (
    <section data-testid="customer-mails"
      className="rounded-lg border border-slate-700 bg-slate-800 p-3 space-y-2">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span className="font-medium text-slate-100">{t('mail.title')}</span>
        {mails.length > 0 && (
          <span data-testid="customer-mails-count"
            className="text-[10px] leading-tight rounded bg-slate-700 text-slate-300 px-1.5 py-0">
            {mails.length}
          </span>
        )}
      </div>
      <p className="text-[11px] text-slate-500">{t('mail.hint')}</p>

      {mails.length === 0 ? (
        <p className="text-xs text-slate-500">{t('mail.none')}</p>
      ) : (
        <ul className="text-sm divide-y divide-slate-700/60">
          {mails.map((a) => (
            <AttachmentRow key={a.id} changeId={changeId} attachment={a} />
          ))}
        </ul>
      )}

      <AttachmentDropzone changeId={changeId} kind="customer_email" compact
        label={t('mail.slot')}
        onUploaded={() => qc.invalidateQueries({ queryKey: ['change', changeId] })} />
    </section>
  )
}
