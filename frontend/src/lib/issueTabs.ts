/**
 * Where validation issues live on the change page. While a fix loops the
 * change back to implementation the issues sit on the Timing tab, next to
 * the recovery blocks in the plan; otherwise on the Release tab.
 */
export type IssueTab = 'timing' | 'release'

export const issueTabFor = (status: string): IssueTab =>
  status === 'in_implementation' ? 'timing' : 'release'

/**
 * The Release tab opens with validation (in_validation). Once an issue
 * exists it stays open from implementation on, so a loop back never hides
 * the validation record.
 */
export const releaseOpenByIssues = (status: string, issueCount: number): boolean =>
  status === 'in_implementation' && issueCount > 0

/** A cockpit action kind that belongs to a validation issue. */
export const isIssueActionKind = (kind: string): boolean => kind.startsWith('validation_issue')
