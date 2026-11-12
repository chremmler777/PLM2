import { createElement, type ReactNode } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { changesChip, lessonsChip, lopChip, useProjectStatus } from './useProjectStatus'
import { getProjectLop } from '../../api/lop'
import { lopLine, lopProject, pdbTopic } from '../../components/lop/lop.fixtures'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
describe('changesChip', () => {
  it('counts only open changes', () => {
    expect(changesChip([{ status: 'scoping' }, { status: 'closed' }, { status: 'rejected' }, { status: 'cancelled' }]).label).toBe('Changes (1)')
    expect(changesChip([]).label).toBe('Changes (0)')
    expect(changesChip(undefined).label).toBe('Changes')
  })
})

describe('lessonsChip', () => {
  it('warns in amber when no lessons review is recorded', () => {
    expect(lessonsChip([])).toEqual({ label: 'Lessons · no review', tone: 'amber', title: 'Gate prep: no lessons review recorded yet' })
    expect(lessonsChip([{}, {}]).label).toBe('Lessons (2)')
    expect(lessonsChip([{}]).label).toBe('Lessons (1)')
    expect(lessonsChip(undefined).label).toBe('Lessons')
  })
})

describe('lopChip', () => {
  it('nav chip counts a late pinned topic and turns amber', () => {
    const pin = pdbTopic({ id: 44, project_id: 2, pinned: true, group: 'overdue', late: true, days_late: 2 })
    const chip = lopChip(lopProject({ lines: [lopLine(), pin] }))
    expect(chip?.label).toBe('LOP 2')
    expect(chip?.tone).toBe('amber')
    expect(lopChip(lopProject({ lines: [lopLine(), { ...pin, late: false }] }))?.tone).toBe('neutral')
  })
})

describe('LOP nav chip query', () => {
  it('asks for the project LOP without the writing sync; the LOP panel keeps the full sync', async () => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) =>
      Promise.resolve({ data: url === '/v1/lop/projects/2' ? lopProject({ lines: [lopLine()] }) : [] }))
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider,
      { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }, children)
    const { result } = renderHook(() => useProjectStatus(2), { wrapper })
    await waitFor(() => expect(result.current.lop?.label).toBe('LOP 1'))
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/lop/projects/2', { params: { view: 'open', sync: false } })
    clientMocks.get.mockClear()
    await getProjectLop(2, 'open')
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/lop/projects/2', { params: { view: 'open' } })
  })
})
