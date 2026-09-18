import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AssemblyTreeList from './AssemblyTreeList'
import client from '../../api/client'

vi.mock('../../api/client', () => ({ default: { get: vi.fn() }, API_BASE_URL: '' }))

const roots = [{ part_id: 1, part_number: 'TOP', name: 'Top', part_type: 'internal_mfg', item_category: 'article',
  revision_id: 11, revision_name: 'E1', revision_phase: 'review', customer_index: 'B', line_count: 2 }]
const tree = { part_id: 1, part_number: 'TOP', name: 'Top', part_type: 'internal_mfg', item_category: 'article',
  revision_id: 11, revision_name: 'E1', revision_phase: 'review', cycle: false, lines: [
    { id: 5, item_number: '10', name: 'SUB', quantity: 2, unit: 'pcs', total_quantity: 2, child_part_id: 2, catalog_part_id: null,
      child: { part_id: 2, part_number: 'SUB', name: 'Sub', part_type: 'internal_mfg', item_category: 'article',
        revision_id: 22, revision_name: '1', revision_phase: 'official', cycle: false, lines: [
          { id: 6, item_number: '10', name: 'BOLT', quantity: 3, unit: 'pcs', total_quantity: 6, child_part_id: 3, catalog_part_id: null,
            child: { part_id: 3, part_number: 'BOLT', name: 'Bolt', part_type: 'purchased', item_category: 'article',
              revision_id: null, revision_name: null, revision_phase: null, cycle: false, lines: [] } }] } },
    { id: 7, item_number: '20', name: 'Glue', quantity: 0.5, unit: 'm', total_quantity: 0.5, child_part_id: null, catalog_part_id: null, child: null },
  ] }

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

describe('AssemblyTreeList', () => {
  beforeEach(() => {
    vi.mocked(client.get).mockImplementation(async (url: string) =>
      url.endsWith('/assemblies') ? { data: roots } : { data: tree })
  })
  afterEach(cleanup)

  it('lists roots and expands into the BOM tree, selecting nested parts', async () => {
    const onSelect = vi.fn()
    wrap(<AssemblyTreeList projectId={9} selectedPartId={null} onSelect={onSelect} />)
    const root = await screen.findByTestId('asm-root-1')
    expect(root.textContent).toContain('TOP')
    expect(root.textContent).toContain('2 lines')
    expect(root.textContent).toContain('E1 · B')
    fireEvent.click(screen.getByTestId('asm-root-toggle-1'))
    await waitFor(() => expect(screen.getByTestId('asm-node-2')).toBeTruthy())
    fireEvent.click(screen.getByTestId('asm-toggle-2'))
    const bolt = await screen.findByTestId('asm-node-3')
    expect(bolt.textContent).toContain('buy')
    fireEvent.click(bolt)
    expect(onSelect).toHaveBeenCalledWith(3)
  })
})
