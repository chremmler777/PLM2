/**
 * One LOP write with its own inline error: the server's `detail` is kept
 * next to the control that sent it (never a toast that disappears), and the
 * LOP queries of the project are refreshed after a success. The live PDB call
 * is refreshed only when the write can change a pinned topic (refreshPdb).
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { lopKeys } from '../../api/lop'
import { apiErrorMessage } from '../../lib/apiError'

export function lopErrorMessage(e: unknown, fallback: string): string {
  const status = (e as { response?: { status?: number } })?.response?.status
  const msg = apiErrorMessage(e, '')
  if (msg) return msg
  if (status === 403) return 'You are not allowed to do that on this project.'
  return fallback
}

export function useLopWrite<V, R = unknown>(
  projectId: number,
  fn: (vars: V) => Promise<R>,
  { fallback = 'That did not work. Try again.', onDone, refreshPdb = true }: {
    fallback?: string; onDone?: (data: R, vars: V) => void; refreshPdb?: boolean
  } = {},
) {
  const qc = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const m = useMutation({
    mutationFn: fn,
    onMutate: () => setError(null),
    onSuccess: (data, vars) => {
      void qc.invalidateQueries({
        queryKey: lopKeys.all(projectId),
        predicate: (q) => refreshPdb || q.queryKey[2] !== 'pdb',
      })
      onDone?.(data, vars)
    },
    onError: (e) => setError(lopErrorMessage(e, fallback)),
  })
  return { run: m.mutate, runAsync: m.mutateAsync, pending: m.isPending, error, clearError: () => setError(null) }
}
