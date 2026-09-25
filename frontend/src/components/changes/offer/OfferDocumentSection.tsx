/**
 * Step 4 of the offer: the letter around the numbers. Recipient, subject and
 * intro, how much of the cost breakdown the customer sees, and the terms. The
 * outline on the right follows the PDF section by section, so Sales sees what
 * the customer will read before opening the preview.
 */
import type { OfferData, OfferOut } from '../../../types/changeOffer'
import { fmtDate, fmtMoney, inputCls, sectionLabel } from './offerFormat'
import { AutoGrowTextarea, Field, Segmented, SubLabel } from './ui'

export default function OfferDocumentSection({
  offer, data, update, editable, changeNumber, onPreview, previewing,
}: {
  offer: OfferOut
  data: OfferData
  update: <K extends keyof OfferData>(key: K, value: OfferData[K]) => void
  editable: boolean
  changeNumber: string
  onPreview: () => void
  previewing?: boolean
}) {
  const recipient = data.recipient ?? {}
  const terms = data.terms ?? {}
  const mode = data.cbd_mode ?? 'detailed'
  const cur = offer.currency || 'EUR'
  const included = (data.cost_lines ?? []).filter((l) => l.include).length
  const shownRisks = (data.risks ?? []).filter((r) => r.show).length
  // The CBD as the customer reads it: included lines grouped by the
  // customer-facing category, when the backend names it.
  const cbd = [...(data.cost_lines ?? []).filter((l) => l.include && l.customer_category)
    .reduce((m, l) => m.set(l.customer_category!, (m.get(l.customer_category!) ?? 0) + (l.amount ?? 0)),
      new Map<string, number>())]
  const changeover = data.changeover?.mode === 'customer_pays_scrap' ? 'Customer pays scrap' : 'Running change'

  const outline: [string, string][] = [
    ['Letterhead', `OFFER ${changeNumber}-Q${offer.version}${offer.valid_until ? `, valid until ${fmtDate(offer.valid_until)}` : ''}`],
    ...(offer.issued_by ? [['Issued by', offer.issued_by] as [string, string]] : []),
    ['Recipient', [recipient.company, recipient.contact].filter(Boolean).join(', ') || 'Not set'],
    ['Subject', data.subject || 'Not set'],
    ['1 Scope of change', data.scope_text?.trim() ? data.scope_text.trim() : 'Not written yet'],
    ['2 Price', mode === 'detailed'
      ? `Detailed CBD, ${cbd.length > 0 ? cbd.map(([k, v]) => `${k} ${fmtMoney(v, cur)}`).join('; ')
        : `${included} line${included === 1 ? '' : 's'}`}, total ${fmtMoney(offer.totals.total_one_time, cur)}`
      : `Rough description, total ${fmtMoney(offer.totals.total_one_time, cur)}`],
    ['3 Changeover', changeover],
    ['4 Timing', data.timing?.include === false ? 'Not included'
      : `${data.timing?.weeks_from_order ?? '-'} weeks from order, draft disclaimer`],
    ['5 Risks and assumptions', shownRisks ? `${shownRisks} risk${shownRisks === 1 ? '' : 's'} shown` : 'None shown'],
    ['6 Terms', [terms.payment, terms.incoterms].filter(Boolean).join(', ') || 'Validity 30 days from receipt'],
    ...(data.customer_note?.trim() ? [['Note to the customer', data.customer_note.trim()] as [string, string]] : []),
  ]
  const recipientMissing = (offer.warnings ?? []).find((w) => w.code === 'recipient_missing')

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_17rem]">
      <div className="space-y-5">
        <div>
          <SubLabel>Recipient</SubLabel>
          <div className="grid gap-2 sm:grid-cols-2">
            <Field label="Company">
              <input className={`${inputCls} w-full`} value={recipient.company ?? ''} disabled={!editable}
                data-testid="doc-company" aria-invalid={recipientMissing && !recipient.company?.trim() ? true : undefined}
                onChange={(e) => update('recipient', { ...recipient, company: e.target.value })} />
              {recipientMissing && !recipient.company?.trim() && (
                <span data-testid="doc-recipient-missing" className="mt-1 block text-[11px] text-amber-300">
                  ⚠ {recipientMissing.message || 'No customer company yet: the offer would go out without a recipient.'}
                </span>
              )}
            </Field>
            <Field label="Contact">
              <input className={`${inputCls} w-full`} value={recipient.contact ?? ''} disabled={!editable}
                onChange={(e) => update('recipient', { ...recipient, contact: e.target.value })} />
            </Field>
            <Field label="Address" className="sm:col-span-2">
              <AutoGrowTextarea rows={4} className={`${inputCls} w-full`} value={recipient.address ?? ''} disabled={!editable}
                data-testid="doc-address"
                onChange={(e) => update('recipient', { ...recipient, address: e.target.value })} />
            </Field>
          </div>
        </div>
        <div className="space-y-2">
          <Field label="Subject">
            <input className={`${inputCls} w-full`} value={data.subject ?? ''} disabled={!editable}
              data-testid="doc-subject" onChange={(e) => update('subject', e.target.value)} />
          </Field>
          <Field label="Intro">
            <textarea rows={3} className={`${inputCls} w-full`} value={data.intro ?? ''} disabled={!editable}
              onChange={(e) => update('intro', e.target.value)} />
          </Field>
          <Field label="Scope of change as the customer reads it (printed as section 1)">
            <AutoGrowTextarea rows={4} data-testid="doc-scope" className={`${inputCls} w-full`}
              value={data.scope_text ?? ''} disabled={!editable}
              placeholder="What changes on the part, in the customer's words. Internal reasons stay out."
              onChange={(e) => update('scope_text', e.target.value)} />
          </Field>
          <Field label="Note to the customer about this version (optional, printed on the offer)">
            <textarea rows={2} data-testid="doc-customer-note" className={`${inputCls} w-full`}
              value={data.customer_note ?? ''} disabled={!editable}
              placeholder="e.g. This version includes the bank build you asked for."
              onChange={(e) => update('customer_note', e.target.value)} />
          </Field>
        </div>
        <div>
          <SubLabel>Price presentation</SubLabel>
          <Segmented testId="cbd-mode" value={mode} disabled={!editable}
            options={[
              { value: 'detailed', label: 'Detailed cost breakdown (CBD)' },
              { value: 'rough', label: 'Rough description' },
            ]}
            onChange={(v) => update('cbd_mode', v)} />
          {mode === 'rough' && (
            <textarea rows={3} data-testid="doc-rough" className={`${inputCls} mt-2 w-full`}
              placeholder="Describe the scope of the price in a few sentences. The customer sees this text and one total."
              value={data.rough_description ?? ''} disabled={!editable}
              onChange={(e) => update('rough_description', e.target.value)} />
          )}
        </div>
        <div>
          <SubLabel>Terms</SubLabel>
          <div className="grid gap-2 sm:grid-cols-3">
            <Field label="Payment">
              <input className={`${inputCls} w-full`} value={terms.payment ?? ''} disabled={!editable}
                onChange={(e) => update('terms', { ...terms, payment: e.target.value })} />
            </Field>
            <Field label="Incoterms">
              <input className={`${inputCls} w-full`} value={terms.incoterms ?? ''} disabled={!editable}
                onChange={(e) => update('terms', { ...terms, incoterms: e.target.value })} />
            </Field>
            <Field label="Delivery">
              <input className={`${inputCls} w-full`} value={terms.delivery ?? ''} disabled={!editable}
                onChange={(e) => update('terms', { ...terms, delivery: e.target.value })} />
            </Field>
            <Field label="Notes" className="sm:col-span-3">
              <textarea rows={2} className={`${inputCls} w-full`} value={terms.notes ?? ''} disabled={!editable}
                onChange={(e) => update('terms', { ...terms, notes: e.target.value })} />
            </Field>
          </div>
          <p className="mt-1 text-[11px] text-slate-500">Validity is fixed: 30 days from the customer's receipt.</p>
        </div>
      </div>

      <aside data-testid="doc-outline" className="self-start rounded-lg border border-slate-700 bg-slate-950/40 p-3">
        <div className="mb-2 flex items-center justify-between">
          <span className={sectionLabel}>PDF outline</span>
          <button type="button" onClick={onPreview} disabled={previewing}
            className="text-xs text-sky-300 hover:text-sky-200 disabled:opacity-50">Preview PDF ↗</button>
        </div>
        <ol className="space-y-1.5">
          {outline.map(([h, body]) => (
            <li key={h} className="border-l-2 border-slate-700 pl-2">
              <div className="text-[11px] font-medium text-slate-300">{h}</div>
              <div className="truncate text-[11px] text-slate-500" title={body}>{body}</div>
            </li>
          ))}
        </ol>
      </aside>
    </div>
  )
}
