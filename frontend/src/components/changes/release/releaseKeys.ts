/** Query key of the release state (checklist + lessons) of a change. */
export const releaseKey = (changeId: number) => ['change', changeId, 'release'] as const
