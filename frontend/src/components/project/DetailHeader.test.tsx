import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import DetailHeader from './DetailHeader'
import type { ArticleSelection } from '../../hooks/useArticleSelection'
import type { Part, PartRevision } from './projectTypes'

vi.mock('../../api/client', () => ({ default: { put: vi.fn() }, API_BASE_URL: '/plm2/api' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const base: Part = {
  id: 5, part_number: '20-1994-005-0', tier1_part_number: 'S00H54-110', customer_part_number: '206.887.233',
  name: 'ISOFIX Cover', part_type: 'internal_mfg', active_revision_id: 9, item_category: 'article', lifecycle_phase: 'nominated',
}
const revisions: PartRevision[] = [{ id: 9, part_id: 5, revision_name: 'E1', customer_index: '001', phase: 'review', status: 'approved', created_at: '2026-09-01' }]

function mount(part: Part) {
  const sel = { partRevisions: revisions, openPart: vi.fn() } as unknown as ArticleSelection
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><DetailHeader projectId={2} part={part} article={undefined} sel={sel} /></MemoryRouter>
    </QueryClientProvider>)
}

describe('DetailHeader', () => {
  afterEach(cleanup)

  it('shows the large thumbnail, the labelled numbers and the revision with our E level bold', () => {
    mount({ ...base, thumbnail_url: '/api/v1/parts/5/thumbnail?v=9' })
    const header = screen.getByTestId('detail-header')
    const thumb = within(header).getByTestId('detail-thumbnail')
    expect(thumb.className).toContain('w-24')
    expect(within(thumb).getByAltText('ISOFIX Cover').getAttribute('src')).toBe('/plm2/api/v1/parts/5/thumbnail?v=9')
    expect(within(header).getByTestId('detail-numbers').textContent).toBe('KTX 20-1994-005-0 · Tier 1 S00H54-110 · OEM 206.887.233')
    const rev = within(header).getByTestId('detail-active-revision')
    expect(rev.textContent).toBe('E1 · 001')
    expect(within(rev).getByText('E1').className).toContain('font-bold')
  })

  it('shows the placeholder without a thumbnail and leaves missing numbers out', () => {
    mount({ ...base, tier1_part_number: null, customer_part_number: null, thumbnail_url: null })
    expect(screen.getByTestId('detail-thumbnail-placeholder')).toBeTruthy()
    expect(screen.getByTestId('detail-numbers').textContent).toBe('KTX 20-1994-005-0')
  })
})
