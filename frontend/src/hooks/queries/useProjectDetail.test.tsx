import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useProject, useProjectParts } from './useProjectDetail'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
)

describe('useProjectDetail queries', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/plants/projects') return Promise.resolve({ data: [{ id: 1, name: 'Other', code: 'X' }, { id: 2, name: 'Atlas', code: '1994' }] })
      if (url === '/v1/parts/project/2') return Promise.resolve({ data: [{ id: 5 }] })
      return Promise.resolve({ data: [] })
    })
  })

  it('picks the project out of the organisation list', async () => {
    const { result } = renderHook(() => useProject(2), { wrapper })
    await waitFor(() => expect(result.current.data?.name).toBe('Atlas'))
  })

  it('loads the project parts', async () => {
    const { result } = renderHook(() => useProjectParts(2), { wrapper })
    await waitFor(() => expect(result.current.data).toEqual([{ id: 5 }]))
  })
})
