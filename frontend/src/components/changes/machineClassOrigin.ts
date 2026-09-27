/**
 * Where a costing line's machine class came from, said in words: "from tool
 * 3454 (MachineDB, 450 t)", "(TWOS, 1,300 t)", or, when no tool of the change
 * has a tonnage, "Tool 3454 has no tonnage: pick a machine class by hand".
 * The class order is: picked on the line > the named press > picked on the
 * change > the change's tool tonnage (MachineDB, then TWOS, then PLM2).
 */
import { t } from '../../i18n/cmLabels'
import { formatNumber } from '../../lib/format'
import type { MachineClassOrigin } from '../../types/change'

const SOURCE_KEY = {
  machinedb: 'costing.tonnageSource.machinedb',
  twos: 'costing.tonnageSource.twos',
  plm2: 'costing.tonnageSource.plm2',
} as const

/** "from tool 3454 (MachineDB, 450 t)"; null for a hand pick or a press. */
export function machineClassOriginText(origin: MachineClassOrigin | null | undefined): string | null {
  if (!origin) return null
  if (origin.kind === 'tool') {
    const tonnage = formatNumber(origin.tonnage)
    const base = t('costing.classFromTool')
      .replace('{tool}', origin.tool_number)
      .replace('{source}', t(SOURCE_KEY[origin.source] ?? origin.source))
      .replace('{t}', tonnage)
    return origin.class_found === false
      ? `${base}: ${t('costing.classNoBand').replace('{t}', tonnage)}`
      : base
  }
  if (origin.kind === 'none') {
    const without = origin.without ?? []
    if (!without.length) return t('costing.noToolOnChange')
    return (without.length === 1 ? t('costing.toolNoTonnage') : t('costing.toolsNoTonnage'))
      .replace('{tools}', without.join(', '))
  }
  if (origin.kind === 'change') return t('costpos.classFromChange')
  return null
}

/** The longer text for a tooltip: which press MachineDB's tonnage is. */
export function machineClassOriginDetail(origin: MachineClassOrigin | null | undefined): string | null {
  const text = machineClassOriginText(origin)
  if (!text || !origin || origin.kind !== 'tool' || origin.source !== 'machinedb') return text
  if (origin.basis === 'assigned' && origin.machine) {
    return `${text}; ${t('costing.tonnageAssigned').replace('{machine}', origin.machine)}`
  }
  if (origin.basis === 'qualified_min') return `${text}; ${t('costing.tonnageQualifiedMin')}`
  return text
}
