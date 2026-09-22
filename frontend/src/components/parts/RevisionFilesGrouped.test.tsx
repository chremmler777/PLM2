import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import RevisionFilesGrouped, { canOpenInline } from './RevisionFilesGrouped'

vi.mock('../../api/client', () => ({ default: { delete: vi.fn() }, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const f = (id: number, filename: string, file_type: string, mime_type: string, has_viewer = false, kind: string | null = null) => ({
  id, revision_id: 9, filename, file_type, mime_type, file_size: 1000, cad_format: null, has_viewer, uploaded_at: '2026-05-28', kind, note: null,
})
const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('RevisionFilesGrouped', () => {
  afterEach(cleanup)

  it('groups into 3D, 2D and Documents with counts and omits empty groups', () => {
    wrap(<RevisionFilesGrouped revisionName="E1" locked={false} viewingFileId={null} onView={() => {}} onOpen={() => {}}
      files={[f(1, 'a.CATPart', 'cad', 'application/octet-stream', false, 'PCA'), f(2, 'a.stp', 'cad', 'application/step', true), f(3, 'd.pdf', 'drawing', 'application/pdf')]} />)
    expect(screen.getByText('3D (2)')).toBeTruthy()
    expect(screen.getByText('2D (1)')).toBeTruthy()
    expect(screen.queryByText(/Documents/)).toBeNull()
    expect(screen.getByText('PCA')).toBeTruthy()
  })

  it('offers Open for pdf and pictures, View 3D for viewable cad', () => {
    const onOpen = vi.fn(); const onView = vi.fn()
    wrap(<RevisionFilesGrouped revisionName="E1" locked={false} viewingFileId={null} onView={onView} onOpen={onOpen}
      files={[f(2, 'a.stp', 'cad', 'application/step', true), f(3, 'd.pdf', 'drawing', 'application/pdf'), f(4, 'p.png', 'picture', 'image/png'), f(5, 'x.xlsx', 'document', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')]} />)
    expect(screen.getAllByText('Open')).toHaveLength(2)
    fireEvent.click(screen.getAllByText('Open')[0])
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }))
    fireEvent.click(screen.getByText('View 3D'))
    expect(onView).toHaveBeenCalledWith(expect.objectContaining({ id: 2 }))
  })

  it('empty state', () => {
    wrap(<RevisionFilesGrouped revisionName="E1" locked={false} viewingFileId={null} onView={() => {}} onOpen={() => {}} files={[]} />)
    expect(screen.getByText('No files on E1 yet')).toBeTruthy()
  })

  it('canOpenInline', () => {
    expect(canOpenInline({ mime_type: 'application/pdf', filename: 'a.pdf' })).toBe(true)
    expect(canOpenInline({ mime_type: 'image/png', filename: 'a.png' })).toBe(true)
    expect(canOpenInline({ mime_type: 'application/octet-stream', filename: 'a.pdf' })).toBe(true)
    expect(canOpenInline({ mime_type: 'application/octet-stream', filename: 'a.CATPart' })).toBe(false)
  })
})
