import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { validationIssuesKey } from '../../../api/validationIssues'
import { releaseKey } from '../release/releaseKeys'

/**
 * The server's reason as text. A 409 from the plan answers an object
 * ({ message, ... }); a 422 a list of { msg }. All read as one sentence.
 */
export const errDetail = (e: unknown): string | undefined => {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof d === 'string') return d
  if (d && typeof d === 'object' && !Array.isArray(d)) {
    const o = d as { message?: unknown; detail?: unknown }
    if (typeof o.message === 'string') return o.message
    if (typeof o.detail === 'string') return o.detail
  }
  if (Array.isArray(d)) {
    const msgs = d.map((x) => (x && typeof x === 'object' ? (x as { msg?: unknown }).msg : null))
      .filter((m): m is string => typeof m === 'string')
    if (msgs.length) return msgs.join('; ')
  }
  return undefined
}

/**
 * One write on an issue. Everything an issue touches is refreshed after it:
 * the list, the change (a route can loop it back to implementation), the
 * release blockers, the validation board, the plan (recovery blocks) and the
 * viewer's actions.
 */
export function useIssueMutation<V>(
  changeId: number,
  fn: (vars: V) => Promise<unknown>,
  opts: { error: string; onDone?: () => void },
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      opts.onDone?.()
      qc.invalidateQueries({ queryKey: validationIssuesKey(changeId) })
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: releaseKey(changeId) })
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? opts.error),
  })
}
