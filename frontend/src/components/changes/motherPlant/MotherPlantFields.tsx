/**
 * The mother-plant half of the Start change dialog (spec 2026-09-25 §14):
 * which mother plant (default Weissenburg), their reference, the SOP date
 * (required: it becomes the release deadline), their documents and,
 * optionally, their timing as an MS Project XML file (it seeds the detailed
 * plan when the change is approved).
 *
 * Kept out of StartChangeModal on purpose: the modal only switches it on and
 * sends what it holds.
 */
import DateInput from '../../gantt/DateInput'
import { t } from '../../../i18n/cmLabels'
import { plantName } from '../../../lib/plantName'

export interface MotherPlantDraft {
  name: string
  ref: string
  /** ISO YYYY-MM-DD, '' while unset. */
  sop: string
  documents: File[]
  timingFile: File | null
}

export const emptyMotherPlantDraft = (defaultName: string): MotherPlantDraft => ({
  name: defaultName, ref: '', sop: '', documents: [], timingFile: null,
})

/** What still has to be filled in before the change can be created. */
export const motherPlantMissing = (d: MotherPlantDraft): string[] =>
  [...(d.name ? [] : [t('mp.plantMissing')]), ...(d.sop ? [] : ['SOP date'])]

const field = 'w-full rounded-lg bg-slate-900 border border-slate-700 px-3 py-2 text-sm'

export default function MotherPlantFields({ value, onChange, plants }: {
  value: MotherPlantDraft
  onChange: (next: MotherPlantDraft) => void
  plants: string[]
}) {
  const set = (patch: Partial<MotherPlantDraft>) => onChange({ ...value, ...patch })
  return (
    <div data-testid="mother-plant-fields"
      className="mb-6 rounded-lg border border-purple-800/60 bg-purple-950/20 p-4 space-y-3">
      <p className="text-xs text-purple-200/80">
        Engineered and sold by {plantName(value.name)}: no assessment, no costing, no offer. You inform
        the team at scoping and take over their timing.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor="sc-mp-name" className="block text-sm text-slate-300 mb-1">{t('mp.plantLabel')}</label>
          <select id="sc-mp-name" className={field} value={value.name}
            onChange={(e) => set({ name: e.target.value })}>
            {plants.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="sc-mp-ref" className="block text-sm text-slate-300 mb-1">Their reference</label>
          <input id="sc-mp-ref" type="text" maxLength={120} className={field}
            placeholder="e.g. their ECR number" value={value.ref}
            onChange={(e) => set({ ref: e.target.value.slice(0, 120) })} />
        </div>
        <div>
          <label htmlFor="sc-mp-sop" className="block text-sm text-slate-300 mb-1">SOP date</label>
          <DateInput id="sc-mp-sop" aria-label="SOP date" value={value.sop}
            className={field} onChange={(iso) => set({ sop: iso })} placeholder="dd.mm.yyyy" commitOnChange />
          <p className="mt-1 text-xs text-slate-500">Becomes the release deadline when the change is approved.</p>
        </div>
        <div>
          <label htmlFor="sc-mp-timing" className="block text-sm text-slate-300 mb-1">
            Their timing <span className="text-slate-500">(MS Project .xml, optional)</span>
          </label>
          <input id="sc-mp-timing" type="file" accept=".xml,application/xml,text/xml"
            className="block w-full text-xs text-slate-300 file:mr-2 file:rounded file:border-0 file:bg-slate-700 file:px-2 file:py-1 file:text-slate-100"
            onChange={(e) => set({ timingFile: e.target.files?.[0] ?? null })} />
          <p className="mt-1 text-xs text-slate-500">Seeds the detailed plan at approval; without it the plan starts from the SOP.</p>
        </div>
      </div>
      <div>
        <label htmlFor="sc-mp-docs" className="block text-sm text-slate-300 mb-1">Their documents</label>
        <input id="sc-mp-docs" type="file" multiple
          className="block w-full text-xs text-slate-300 file:mr-2 file:rounded file:border-0 file:bg-slate-700 file:px-2 file:py-1 file:text-slate-100"
          onChange={(e) => set({ documents: Array.from(e.target.files ?? []) })} />
        {value.documents.length > 0 && (
          <p className="mt-1 text-xs text-slate-400">{value.documents.map((f) => f.name).join(', ')}</p>
        )}
      </div>
    </div>
  )
}
