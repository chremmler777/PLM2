import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RevisionFileRow } from './ProjectDetailPage'

vi.mock('../api/client', () => ({ default: { get: vi.fn(), delete: vi.fn() }, API_BASE_URL: '' }))

const file = (over: Record<string, unknown> = {}) => ({
  id: 3, revision_id: 9, filename: 'housing.step', file_type: 'cad_native',
  mime_type: 'application/step', file_size: 2_000_000, cad_format: 'step',
  has_viewer: true, uploaded_at: '2026-07-01T00:00:00', ...over,
}) as never

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('RevisionFileRow provenance', () => {
  afterEach(cleanup)

  it('names who uploaded the revision file and when', () => {
    wrap(<RevisionFileRow file={file({ uploaded_by: 5, uploaded_by_name: 'Eva Eng' })}
      isViewing={false} locked={false} />)
    expect(screen.getByTestId('uploaded-by').textContent)
      .toContain(`Eva Eng · ${new Date('2026-07-01T00:00:00').toLocaleDateString()}`)
  })

  it('shows the date alone for a file with no recorded uploader', () => {
    wrap(<RevisionFileRow file={file()} isViewing={false} locked={false} />)
    expect(screen.getByTestId('uploaded-by').textContent).not.toContain('·')
  })
})
