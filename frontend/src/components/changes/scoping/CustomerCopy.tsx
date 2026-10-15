/**
 * The mail text of a customer question (spec §0 [R4], §3): built by the
 * backend from the picks (what is asked, the part, what the answer
 * decides). Sales reads it and copies it into the mail to the customer.
 */
import { useState } from 'react'
import { toast } from 'sonner'
import { btnSm } from '../../common/buttonStyles'
import { t } from '../../../i18n/cmLabels'

export default function CustomerCopy({ text, testId }: { text: string; testId: string }) {
  const [open, setOpen] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      toast.success(t('copy.done'))
    } catch {
      // no clipboard (insecure context, denied): the text is shown to copy by hand
      setOpen(true)
      toast.error(t('copy.failed'))
    }
  }
  return (
    <div className="space-y-1" data-testid={testId}>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btnSm.secondary} data-testid={`${testId}-copy`}
          onClick={() => { void copy() }}>
          {t('copy.mailText')}
        </button>
        <button type="button" className="text-xs text-slate-400 hover:text-slate-200"
          aria-expanded={open} onClick={() => setOpen((v) => !v)}>
          {open ? t('copy.hide') : t('copy.show')}
        </button>
      </div>
      {open && (
        <pre className="whitespace-pre-wrap rounded border border-slate-700 bg-slate-900 p-2 text-xs text-slate-200">
          {text}
        </pre>
      )}
    </div>
  )
}
