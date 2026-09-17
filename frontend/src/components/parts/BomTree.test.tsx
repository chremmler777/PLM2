import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import BomTree, { type BomNode } from './BomTree'

const node = (over: Partial<BomNode>): BomNode => ({
  part_id: 1, part_number: 'TOP', name: 'Top', part_type: 'internal_mfg', item_category: 'article',
  revision_id: 1, revision_name: 'E1', revision_phase: 'review', cycle: false, lines: [], ...over,
})

const tree: BomNode = node({
  lines: [
    { id: 10, item_number: '10', name: 'SUB', quantity: 2, unit: 'pcs', total_quantity: 2, child_part_id: 2, catalog_part_id: null,
      child: node({ part_id: 2, part_number: 'SUB', name: 'Sub', revision_name: '1', revision_phase: 'official',
        lines: [{ id: 20, item_number: '10', name: 'BOLT', quantity: 3, unit: 'pcs', total_quantity: 6, child_part_id: 3, catalog_part_id: null,
          child: node({ part_id: 3, part_number: 'BOLT', name: 'Bolt', part_type: 'purchased', revision_id: null, revision_name: null, revision_phase: null }) }] }) },
    { id: 11, item_number: '20', name: 'Glue', quantity: 0.5, unit: 'm', total_quantity: 0.5, child_part_id: null, catalog_part_id: null, child: null },
  ],
})

describe('BomTree', () => {
  afterEach(cleanup)

  it('renders nested lines with multiplied totals and badges', () => {
    render(<BomTree tree={tree} />)
    expect(screen.getByTestId('bom-line-10').textContent).toContain('SUB')
    expect(screen.getByTestId('bom-rev-10').textContent).toBe('1')
    expect(screen.getByTestId('bom-rev-10').getAttribute('title')).toBe('official')
    const bolt = screen.getByTestId('bom-line-20')
    expect(bolt.textContent).toContain('purchased')
    expect(bolt.textContent).toContain('no data')
    expect(screen.getByTestId('bom-total-20').textContent).toContain('Σ 6')
    expect(screen.getByTestId('bom-line-11').textContent).toContain('Glue')
  })

  it('collapses a sub-assembly', () => {
    render(<BomTree tree={tree} />)
    fireEvent.click(screen.getByTestId('bom-toggle-10'))
    expect(screen.queryByTestId('bom-line-20')).toBeNull()
  })
})
