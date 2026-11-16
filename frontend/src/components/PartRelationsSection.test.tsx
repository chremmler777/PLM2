import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PartRelationsSection from './PartRelationsSection'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

describe('PartRelationsSection relation type select', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation(() => Promise.resolve({ data: [] }))
  })
  afterEach(cleanup)

  it('offers "mirror of" for an article', async () => {
    wrap(<PartRelationsSection partId={1} itemCategory="article" projectParts={[]} />)
    fireEvent.click(screen.getByText('+ Link Item'))
    const option = await screen.findByRole('option', { name: 'mirror of' }) as HTMLOptionElement
    expect(option.value).toBe('mirror_of')
  })

  it('does not offer "mirror of" for a tool', async () => {
    wrap(<PartRelationsSection partId={1} itemCategory="tool" projectParts={[]} />)
    fireEvent.click(screen.getByText('+ Link Item'))
    expect(screen.queryByRole('option', { name: 'mirror of' })).toBeNull()
  })

  describe('rights for gauge and equipment links', () => {
    const relations = [
      { id: 1, relation_type: 'checks', direction: 'incoming', label: 'checked by', other_part_id: 3, other_part_number: '3345-40', other_part_name: 'Gauge', other_item_category: 'gauge', notes: null },
      { id: 2, relation_type: 'assembles', direction: 'incoming', label: 'assembled by', other_part_id: 4, other_part_number: '3345-20', other_part_name: 'Station', other_item_category: 'assembly_equipment', notes: null },
      { id: 3, relation_type: 'related', direction: 'outgoing', label: 'related to', other_part_id: 5, other_part_number: '1748-0013', other_part_name: 'Cover RH', other_item_category: 'article', notes: null },
    ]
    const withRights = (rights: Record<string, boolean>, rels: unknown[] = relations) =>
      clientMocks.get.mockImplementation((url: string) => Promise.resolve({ data: url === '/v1/auth/me' ? rights : rels }))

    it('hides remove and the link kinds the viewer has no right for', async () => {
      withRights({ can_edit_tools: false, can_edit_gauges: true, can_edit_assembly_equipment: false })
      wrap(<PartRelationsSection partId={1} itemCategory="article" projectParts={[]} />)
      expect(await screen.findByLabelText('Remove link to 3345-40')).toBeTruthy()
      await waitFor(() => expect(screen.queryByLabelText('Remove link to 3345-20')).toBeNull())
      expect(screen.getByLabelText('Remove link to 1748-0013')).toBeTruthy()
      fireEvent.click(screen.getByText('+ Link Item'))
      const kinds = Array.from((screen.getByLabelText('Kind of link') as HTMLSelectElement).options).map((o) => o.value)
      expect(kinds).toEqual(['checks', 'related', 'mirror_of'])
    })

    it('a gauge page has no add button without the gauge right, and offers "serves" with it', async () => {
      withRights({ can_edit_tools: false, can_edit_gauges: false, can_edit_assembly_equipment: true }, [])
      wrap(<PartRelationsSection partId={3} itemCategory="gauge" projectParts={[]} />)
      await waitFor(() => expect(screen.queryByText('+ Link Item')).toBeNull())
      cleanup()
      withRights({ can_edit_tools: false, can_edit_gauges: true, can_edit_assembly_equipment: false }, [])
      wrap(<PartRelationsSection partId={3} itemCategory="gauge" projectParts={[]} />)
      fireEvent.click(screen.getByText('+ Link Item'))
      expect(await screen.findByRole('option', { name: 'serves (tool)' })).toBeTruthy()
    })

    it('a "serves" link is removable by the right of the serving item', async () => {
      withRights({ can_edit_tools: true, can_edit_gauges: false, can_edit_assembly_equipment: true }, [
        { id: 7, relation_type: 'serves', direction: 'incoming', label: 'served by', other_part_id: 3, other_part_number: '3345-40', other_part_name: 'Gauge', other_item_category: 'gauge', notes: null },
        { id: 8, relation_type: 'serves', direction: 'incoming', label: 'served by', other_part_id: 4, other_part_number: '3345-10', other_part_name: 'EOAT', other_item_category: 'assembly_equipment', notes: null },
      ])
      wrap(<PartRelationsSection partId={1} itemCategory="tool" projectParts={[]} />)
      expect(await screen.findByLabelText('Remove link to 3345-10')).toBeTruthy()
      await waitFor(() => expect(screen.queryByLabelText('Remove link to 3345-40')).toBeNull())
    })
  })
})
