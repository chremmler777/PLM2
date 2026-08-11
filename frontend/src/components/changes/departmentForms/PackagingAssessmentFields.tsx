/**
 * Packaging Engineer's questionnaire.
 *
 * The first question decides everything: if packaging is not impacted, that IS
 * the assessment — one click, recorded, done. Only when it is impacted does the
 * detail appear, because only then is there anything to say.
 */
import { useState } from 'react'
import { t } from '../../../i18n/cmLabels'
import type { DepartmentFieldsProps } from './types'

const BOXES: { key: string; label: string }[] = [
  { key: 'layout_change', label: 'pkg.layout' },
  { key: 'packaging_type_change', label: 'pkg.type' },
  { key: 'packaging_modification', label: 'pkg.modify' },
]

export default function PackagingAssessmentFields({ value, onChange }: DepartmentFieldsProps) {
  const impacted = value.impacted as boolean | undefined
  const [checked, setChecked] = useState<Record<string, boolean>>(
    Object.fromEntries(BOXES.map((b) => [b.key, !!value[b.key]])))

  const setBox = (key: string, on: boolean) => {
    const next = { ...checked, [key]: on }
    setChecked(next)
    onChange({ ...value, ...next })
  }

  return (
    <div className="space-y-2">
      <fieldset>
        <legend className="block text-xs text-slate-500 mb-1">{t('pkg.impacted')}</legend>
        <div className="flex items-center gap-3 text-sm">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="radio" name="pkg-impacted" data-testid="pkg-impacted-yes"
              checked={impacted === true}
              onChange={() => onChange({ ...value, ...checked, impacted: true })} />
            <span>{t('common.yes')}</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="radio" name="pkg-impacted" data-testid="pkg-impacted-no"
              checked={impacted === false}
              onChange={() => onChange({ impacted: false })} />
            <span>{t('common.no')}</span>
          </label>
        </div>
      </fieldset>

      {impacted === true && (
        <div className="space-y-1" data-testid="pkg-detail">
          {BOXES.map((b) => (
            <label key={b.key} className="flex items-center gap-2 text-sm cursor-pointer">
              <input type="checkbox" data-testid={`pkg-${b.key}`}
                checked={!!checked[b.key]}
                onChange={(e) => setBox(b.key, e.target.checked)} />
              <span>{t(b.label)}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}
