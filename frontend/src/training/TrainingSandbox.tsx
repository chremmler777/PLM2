import { useEffect, useMemo, useRef, useState } from 'react'
import type { AxiosAdapter } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import client, { networkClient } from '../api/client'
import { createTrainingAdapter } from './sandbox/adapter'
import { sandboxClosed, sandboxOpened } from './sandbox/containment'
import { clearSeedDrafts, createSandbox, type SandboxState } from './sandbox/state'
import { InTrainingSandbox } from './context'

//: Mounts a real PLM2 screen against the training fixture (ported from TWOS).
//:
//: On mount the training adapter goes onto the shared axios client, which
//: every api module imports; on unmount it comes off again. While it is
//: installed the screens inside run their real code and reach the fixture
//: instead of the network.
//:
//: The query client is its own and is thrown away with the sandbox, so
//: nothing done here can be served out of cache to the live app afterwards.
//:
//: Render this only on a page outside AppLayout (the training run page): the
//: sidebar polls the live API, and while the adapter is installed those polls
//: would be answered, or refused, by the sandbox.

interface Props {
  /** Re-created whenever this changes, so each task starts from a clean fixture. */
  resetKey: string | number
  children: (state: SandboxState) => React.ReactNode
}

/**
 * Installs the adapter for `state`, and reports which state it is installed
 * for. The caller renders nothing until it matches: effects run after the
 * commit, so a plain boolean would let the next task's screen mount and fire
 * its queries against the previous adapter, or none (TWOS, 2026-08-04).
 */
function useSandboxAdapter(state: SandboxState | null): SandboxState | null {
  const [installedFor, setInstalledFor] = useState<SandboxState | null>(null)
  const previous = useRef<AxiosAdapter | undefined>(undefined)

  useEffect(() => {
    if (!state) return
    previous.current = client.defaults.adapter as AxiosAdapter | undefined
    client.defaults.adapter = createTrainingAdapter(
      state,
      (c) => networkClient.request(c),
    ) as AxiosAdapter
    sandboxOpened()
    setInstalledFor(state)
    return () => {
      client.defaults.adapter = previous.current
      sandboxClosed()
      clearSeedDrafts()
      setInstalledFor(null)
    }
  }, [state])

  return installedFor
}

export default function TrainingSandbox({ resetKey, children }: Props) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const state = useMemo(() => createSandbox(), [resetKey])
  const qc = useMemo(
    () =>
      new QueryClient({
        //: No retries and no stale window: the sandbox answers at once and the
        //: trainee must see the effect of what they just did, immediately.
        defaultOptions: { queries: { retry: false, staleTime: 0, gcTime: 0 } },
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [resetKey],
  )
  const installedFor = useSandboxAdapter(state)

  useEffect(() => () => qc.clear(), [qc])

  //: Not "is something installed" but "is *this* state installed".
  if (installedFor !== state) return null
  return (
    <InTrainingSandbox.Provider value={true}>
      <QueryClientProvider client={qc} key={String(resetKey)}>
        <div
          data-testid="training-sandbox"
          className="rounded-lg border-2 border-dashed border-amber-500/60 bg-amber-500/[0.03]"
        >
          <div className="flex items-center gap-2 px-3 py-1.5 border-b border-amber-500/30">
            <span className="inline-flex items-center rounded-full bg-amber-500 px-2 py-px font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-900">
              Training
            </span>
            <span className="text-[12px] text-amber-200/90">
              Practice copy. Nothing here reaches the live system.
            </span>
          </div>
          <div className="p-4">{children(state)}</div>
        </div>
      </QueryClientProvider>
    </InTrainingSandbox.Provider>
  )
}
