import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import SepDocumentsTab from './SepDocumentsTab'

const clientMocks = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))

const wrap = (ui: React.ReactElement) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      {ui}
    </QueryClientProvider>)

const payload = [
  {
    gate_id: 1, gate_code: 'QG1', phase_en: 'Concept', seq: 1,
    items: [{
      item_id: 7, item_no: 12, title_en: 'Feasibility study', department: 'Engineering',
      files: [{
        id: 11, item_id: 7, filename: 'feasibility.pdf', content_type: 'application/pdf',
        size_bytes: 1024, sha256: 'a', uploaded_by: 3, uploaded_by_name: 'Eva Eng',
        uploaded_at: '2026-09-01T00:00:00',
      }],
    }],
  },
  {
    gate_id: 2, gate_code: 'QG2', phase_en: 'Development', seq: 2,
    items: [{
      item_id: 20, item_no: 4, title_en: 'DFMEA', department: 'Quality',
      files: [{
        id: 30, item_id: 20, filename: 'dfmea.xlsx', content_type: 'application/xlsx',
        size_bytes: 3_000_000, sha256: 'b', uploaded_by: null, uploaded_by_name: null,
        uploaded_at: '2026-09-02T00:00:00',
      }],
    }],
  },
]

describe('SepDocumentsTab', () => {
  beforeEach(() => clientMocks.get.mockReset())
  afterEach(cleanup)

  it('groups the project files by gate and topic, each a download link', async () => {
    clientMocks.get.mockResolvedValue({ data: payload })
    wrap(<SepDocumentsTab projectId={2} />)

    expect(await screen.findByTestId('sep-doc-gate-1')).toBeTruthy()
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/sep/projects/2/files')
    expect(screen.getByTestId('sep-doc-gate-1').textContent).toContain('QG1 — Concept')
    expect(screen.getByTestId('sep-doc-item-7').textContent).toContain('Feasibility study')
    expect(screen.getByTestId('sep-doc-item-20').textContent).toContain('DFMEA')

    expect(screen.getByText('feasibility.pdf').getAttribute('href'))
      .toContain('/v1/sep/items/7/files/11/download')
    expect(screen.getByText('dfmea.xlsx').getAttribute('href'))
      .toContain('/v1/sep/items/20/files/30/download')
  })

  it('invites a first drop when the project has no documents', async () => {
    clientMocks.get.mockResolvedValue({ data: [] })
    wrap(<SepDocumentsTab projectId={2} />)
    expect((await screen.findByTestId('sep-documents-empty')).textContent)
      .toContain('No documents yet. Drop files on a topic to collect them.')
  })
})
