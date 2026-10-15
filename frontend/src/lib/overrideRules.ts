import type { DeciderGroup } from '../types/change'
import { t } from '../i18n/cmLabels'

/**
 * C6 (spec §0 "Override"): who gives the OK on an override, mirrored from
 * backend cm_rules.decider_group so the dialog can say "needs <who>'s OK"
 * before anything is asked. The backend stays the judge.
 */
const PM_MGMT_RULES = new Set(['scope_change_uncovered', 'price_drop', 'price_open'])
const QUALITY_RULES = new Set(['validation_open', 'validation_failed', 'validation_issues_open'])
const QUALITY_TARGETS = new Set(['in_implementation', 'released'])
/** Rules decided, never overridden (backend cm_rules.DECIDE_ONLY_RULES). */
export const DECIDE_ONLY_RULES = new Set(['routing_deviation_pending'])

export function deciderGroup(rule: string | null | undefined, to: string, customerRelevant = true): DeciderGroup {
  if (rule === 'price_open') return customerRelevant ? 'pm_mgmt' : 'approver'
  if (rule && PM_MGMT_RULES.has(rule)) return 'pm_mgmt'
  if ((rule && QUALITY_RULES.has(rule)) || QUALITY_TARGETS.has(to)) return 'quality'
  return 'run'
}

/** "the lead (Anna Berg), a Project Management member or an admin". */
export function deciderText(group: DeciderGroup, leadName?: string | null): string {
  if (group === 'run') {
    return leadName ? t('override.whoRunLead').replace('{lead}', leadName) : t('override.whoRun')
  }
  return t(`override.who.${group}`)
}

/** The reason pick of every override (backend cm_rules.OVERRIDE_REASONS). */
export const OVERRIDE_REASONS = ['customer_date', 'in_parallel', 'not_applicable', 'other'] as const
/** Why an open price is absorbed (backend cm_rules.ABSORB_REASONS). */
export const ABSORB_REASONS = ['goodwill', 'small_amount', 'our_error', 'other'] as const

/** R4 (backend cm_rules.override_note_refusal): a note is a sentence, not
 * a word; "customer date" names the date or the mail. */
export const NOTE_MIN_CHARS = 15
const EMPTY_WORDS = new Set(['ok', 'okay', 'tbd', 'na', 'n/a', 'done', 'checked', 'yes', '-', '--'])

/** Why this note does not do yet (a sentence to show), or null. */
export function overrideNoteProblem(code: string, note: string): string | null {
  const v = note.trim()
  if (v.length < NOTE_MIN_CHARS || EMPTY_WORDS.has(v.toLowerCase())) {
    return t('override.noteTooShort').replace('{n}', String(NOTE_MIN_CHARS))
  }
  if (code === 'customer_date' && !/\d/.test(v)) return t('override.noteNeedsDate')
  return null
}

/** A rule's name for people: `rule.<key>`, a gate by its D1 question. */
export function ruleText(rule: string | null | undefined): string {
  if (!rule) return t('override.anyRule')
  if (rule.startsWith('gate:')) return `${t('gate.' + rule.slice(5))} ${t('cockpit.gateWord')}`
  return t('rule.' + rule)
}
