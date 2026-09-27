/**
 * Scoping and concern rules (spec §16), kept apart from the components so they
 * can be shared and tested on their own.
 */
import { t } from '../i18n/cmLabels'
import { preferredDepartmentId } from './departments'
import type { Contact } from '../api/contacts'
import type { ChangeConcern, CostCarrier } from '../types/change'

/**
 * The attendee picker offers people only: the contact source also knows
 * department mailboxes, distribution lists and system senders, and none of
 * them sits in a meeting.
 */
export function isPersonContact(c: Contact, departmentNames: string[] = []): boolean {
  const name = (c.name ?? '').trim()
  if (!name || !/[a-z]/i.test(name)) return false
  const lower = name.toLowerCase()
  if (departmentNames.some((d) => d.toLowerCase() === lower)) return false
  if (c.source && /group|department|distribution|shared|room|system/i.test(c.source)) return false
  const local = (c.email ?? '').split('@')[0].toLowerCase()
  if (/^(no-?reply|noreply|info|team|sales|support|admin|service|office|plm|notifications?)([._-]|$)/.test(local)) return false
  if (/^(team|all|dl|grp|group)\b|\b(team|group|department|mailbox)$/i.test(lower)) return false
  return true
}

/** The room's cost carrier as a form value, from the change's flag. */
export const carrierOf = (customerRelevant?: boolean | null): CostCarrier | '' =>
  customerRelevant === true ? 'customer' : customerRelevant === false ? 'internal' : ''

/**
 * Which department a new flag is filed under by default: the viewer's own.
 * The first membership that is on this change, else Development (the master
 * role), else the first membership offered; nothing when the viewer has none.
 */
export function defaultFlagDepartment(
  membershipIds: number[], options: { id: number; name: string }[],
  changeDepartmentIds: number[] = [],
): number | undefined {
  const offered = options.filter((d) => membershipIds.includes(d.id))
  return offered.find((d) => changeDepartmentIds.includes(d.id))?.id
    ?? preferredDepartmentId(membershipIds, offered)
    ?? offered[0]?.id
}

/**
 * How a closed flag ended, in words: its author withdrew it, or someone else
 * (the PM in scoping, the raising department in assessment) settled it.
 */
export function settledLine(c: ChangeConcern, scoped: boolean): string {
  const byAuthor = c.settled_as === 'withdrawn'
    || (c.settled_as == null && c.withdrawn_by != null && c.withdrawn_by === c.raised_by)
  if (byAuthor) return t('concern.withdrawnByAuthor')
  if (c.withdrawn_by == null && !c.withdrawn_by_name) {
    return c.withdrawn_at ? t('concern.withdrawn') : t('concern.answered')
  }
  const who = c.withdrawn_by_name ?? `#${c.withdrawn_by}`
  // In scoping only the author or the PM may close a flag: anyone else is the PM.
  return scoped ? t('concern.settledBy').replace('{x}', who) : t('concern.settledByPm').replace('{x}', who)
}

/**
 * Who a pending routing change waits on, in words. Mirrors
 * ChangeRoutingService.user_can_decide_deviation: never the proposer; a
 * non-lead's proposal is the lead's call, the lead's own proposal goes to the
 * Project Manager; with no lead, anyone but the proposer.
 */
export function deviationWaitKey(
  proposedBy: number | null | undefined, leadId: number | null | undefined,
  viewerId: number | null | undefined,
): string {
  if (proposedBy != null && viewerId != null && proposedBy === viewerId) return 'routingDev.waitingYou'
  if (leadId === undefined) return 'routingDev.waitingForLead'
  if (leadId === null) return 'routingDev.waitingForAnyone'
  if (proposedBy != null && proposedBy === leadId) return 'routingDev.waitingForPm'
  return 'routingDev.waitingForLead'
}
