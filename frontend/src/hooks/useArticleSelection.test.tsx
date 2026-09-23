import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useArticleSelection } from './useArticleSelection'
import type { Part } from '../components/project/projectTypes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const parts: Part[] = [
  { id: 5, part_number: '20-1', name: 'Cover', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', parent_part_id: null },
  { id: 6, part_number: '20-2', name: 'Lid', part_type: 'internal_mfg', active_revision_id: null, item_category: 'article', parent_part_id: null },
]
const rev = (id: number, part_id: number, revision_name: string) =>
  ({ id, part_id, revision_name, phase: 'review', status: 'draft', created_at: '2026-05-28' })

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
)

describe('useArticleSelection', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5/revisions') return Promise.resolve({ data: [rev(9, 5, 'E1'), rev(10, 5, 'E1.1')] })
      if (url === '/v1/parts/6/revisions') return Promise.resolve({ data: [rev(20, 6, 'E1'), rev(21, 6, 'E2')] })
      return Promise.resolve({ data: [] })
    })
  })

  it('selects the active revision once the revisions load', async () => {
    const { result } = renderHook(() => useArticleSelection(parts, 5), { wrapper })
    await waitFor(() => expect(result.current.revisionId).toBe(9))
  })

  it('falls back to the latest revision when the part has no active one', async () => {
    const { result } = renderHook(() => useArticleSelection(parts, 6), { wrapper })
    await waitFor(() => expect(result.current.revisionId).toBe(21))
  })

  it('lets an explicit pick win over the active revision', async () => {
    const { result } = renderHook(() => useArticleSelection(parts, null), { wrapper })
    act(() => result.current.pickRevision(5, 10))
    await waitFor(() => expect(result.current.partRevisions?.length).toBe(2))
    expect(result.current.revisionId).toBe(10)
  })

  it('drops a pick for a part that turns out to have no revisions', async () => {
    const { result } = renderHook(() => useArticleSelection([...parts, { ...parts[1], id: 7 }], 5), { wrapper })
    await waitFor(() => expect(result.current.revisionId).toBe(9))
    act(() => result.current.pickRevision(7, 99))
    await waitFor(() => expect(result.current.partRevisions).toEqual([]))
    expect(result.current.revisionId).toBeNull()
  })

  it('openPart resets the document view even for the same part', async () => {
    const { result } = renderHook(() => useArticleSelection(parts, 5), { wrapper })
    await waitFor(() => expect(result.current.revisionId).toBe(9))
    act(() => { result.current.setViewingFileId(3); result.current.setOpenDocId(4) })
    expect(result.current.viewingFileId).toBe(3)
    act(() => result.current.openPart(5))
    expect(result.current.viewingFileId).toBeNull()
    expect(result.current.openDocId).toBeNull()
  })
})
