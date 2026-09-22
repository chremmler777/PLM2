import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import PartDetail from './PartDetail'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('../components/Viewer3D', () => ({ default: () => <div>viewer</div> }))
vi.mock('../components/paint/PartPaintCard', () => ({ default: () => <div>paint</div> }))
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ isAdmin: true }) }))
vi.mock('../components/parts/BomTree', () => ({ default: () => <div>bom-tree</div> }))

describe('PartDetail files card', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/parts/5') return Promise.resolve({ data: { id: 5, project_id: 2, part_number: '20-1', name: 'Cover', part_type: 'internal_mfg', item_category: 'article', active_revision_id: 9, lifecycle_phase: 'rfq',
        revisions: [{ id: 9, revision_name: 'E1', phase: 'review', status: 'approved', parent_revision_id: null, source: 'customer', customer_index: '003', part_phase_at_receipt: 'rfq', created_at: '2026-05-28' }] } })
      if (url === '/v1/parts/revisions/9/files') return Promise.resolve({ data: [
        { id: 103, revision_id: 9, filename: 'd.pdf', file_type: 'drawing', mime_type: 'application/pdf', file_size: 1, cad_format: null, has_viewer: false, uploaded_at: '2026-05-28' }] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('lists the active revision files grouped and opens a drawing inline', async () => {
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/parts/5']}><Routes><Route path="/parts/:partId" element={<PartDetail />} /></Routes></MemoryRouter></QueryClientProvider>)
    expect(await screen.findByText('2D (1)')).toBeTruthy()
    fireEvent.click(screen.getByText('Open'))
    expect((await screen.findByTestId('doc-iframe') as HTMLIFrameElement).src).toContain('/v1/parts/revision-files/103/inline')
  })
})
