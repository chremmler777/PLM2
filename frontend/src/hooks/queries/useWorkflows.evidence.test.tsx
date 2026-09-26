import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useRevisionWorkflow, invalidateRevisionWorkflow } from './useWorkflows'
import * as workflowApi from '../../api/workflows'

vi.mock('../../api/workflows', () => ({ getRevisionWorkflow: vi.fn() }))

describe('useRevisionWorkflow and 3D evidence', () => {
  afterEach(cleanup)

  it('refetches on remount even under a long global staleTime (evidence changes outside the workflow)', async () => {
    const get = vi.mocked(workflowApi.getRevisionWorkflow)
    get.mockResolvedValueOnce({ id: 1, has_3d_evidence: false } as never)
      .mockResolvedValueOnce({ id: 1, has_3d_evidence: true } as never)
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
    const wrapper = ({ children }: { children: React.ReactNode }) =>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    const first = renderHook(() => useRevisionWorkflow(7), { wrapper })
    await waitFor(() => expect(first.result.current.data?.has_3d_evidence).toBe(false))
    first.unmount()
    const second = renderHook(() => useRevisionWorkflow(7), { wrapper })
    await waitFor(() => expect(second.result.current.data?.has_3d_evidence).toBe(true))
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('invalidateRevisionWorkflow targets the one revision, or every revision instance without an id', () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    invalidateRevisionWorkflow(qc, 7)
    invalidateRevisionWorkflow(qc)
    expect(spy).toHaveBeenNthCalledWith(1, { queryKey: ['workflow', 'revision', 7, 'instance'] })
    expect(spy).toHaveBeenNthCalledWith(2, { queryKey: ['workflow', 'revision'] })
  })
})
