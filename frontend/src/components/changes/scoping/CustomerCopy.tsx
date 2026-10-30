/**
 * The mail text of a customer question (spec §0 [R4], §3): built by the
 * backend from the picks (what is asked, the part, what the answer
 * decides). Sales reads it and copies it into the mail to the customer.
 */
import { useState } from 'react'
import { toast } from 'sonner'
import { btnSm } from '../../common/buttonStyles'
import { t } from '../../../i18n/cmLabels'

/** The clipboard API needs https; on plain http (a local or test server)
 *  the old select-and-copy still works (Christoph 2026-10-30). */
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to the select-and-copy below
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    document.body.removeChild(area)
  }
}

export default function CustomerCopy({ text, testId }: { text: string; testId: string }) {
  const [open, setOpen] = useState(false)
  const copy = async () => {
    if (await copyText(text)) {
      toast.success(t('copy.done'))
    } else {
      // no clipboard at all: the text is shown to copy by hand
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
        <div className="relative">
          <pre className="whitespace-pre-wrap rounded border border-slate-700 bg-slate-900 p-2 pr-20 text-xs text-slate-200">
            {text}
          </pre>
          <button type="button" className={`${btnSm.secondary} absolute right-2 top-2`}
            data-testid={`${testId}-copy-box`} onClick={() => { void copy() }}>
            {t('copy.short')}
          </button>
        </div>
      )}
    </div>
  )
}
