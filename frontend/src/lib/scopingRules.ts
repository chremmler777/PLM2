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

/**
 * Who may answer a scoping question (2026-10-14): the question stays the
 * ASKING side's task. Members of the department it was asked for (with none,
 * its author), Sales and Project Management answer it. The backend serves the
 * verdict per question (`can_answer`, MeetingService.can_answer_question);
 * the rest mirrors it for an older payload. Acting as a department is exactly
 * that department: personal authorship steps aside.
 */
export function canAnswerQuestion(
  c: ChangeConcern,
  viewer: {
    userId?: number | null; actingAs?: boolean; isSales?: boolean; isPm?: boolean
    myDepartmentIds?: number[]
  },
): boolean {
  if (c.can_answer != null) return c.can_answer
  if (!c.is_open) return false
  if (viewer.isSales || viewer.isPm) return true
  if (c.department_id != null) return (viewer.myDepartmentIds ?? []).includes(c.department_id)
  return !viewer.actingAs && viewer.userId != null && c.raised_by === viewer.userId
}

/** The side a question is waiting on, in words: its department, else its author. */
export function askingSide(c: ChangeConcern, departmentName?: (id: number) => string | undefined): string {
  return c.asking_department_name
    ?? (c.department_id != null ? departmentName?.(c.department_id) : undefined)
    ?? c.raised_by_name ?? `#${c.raised_by}`
}

/** Open flags that block 'proceed' (risks never do), as dialog lines:
 *  "Question · Anna (APQP): tolerance?" */
export function openFlagLines(
  concerns: ChangeConcern[], departmentName?: (id: number) => string | undefined,
): string[] {
  return concerns
    .filter((c) => c.is_open && c.kind !== 'risk')
    .sort((a, b) => a.id - b.id)
    .map((c) => {
      const kind = c.kind === 'needs_info' ? t('concern.kind.question')
        : c.kind === 'reject_proposal' ? t('concern.kind.cancelVote') : c.kind
      const dept = c.asking_department_name
        ?? (c.department_id != null ? departmentName?.(c.department_id) : undefined)
      const who = `${c.raised_by_name ?? `#${c.raised_by}`}${dept ? ` (${dept})` : ''}`
      return `${kind} · ${who}: ${c.note}`
    })
}
