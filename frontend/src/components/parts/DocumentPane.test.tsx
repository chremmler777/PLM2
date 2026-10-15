import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import DocumentPane from './DocumentPane'

vi.mock('../../api/client', () => ({ default: {}, API_BASE_URL: '/api' }))

describe('DocumentPane', () => {
  afterEach(cleanup)

  it('shows a picture inline with the file and revision named', () => {
    render(<DocumentPane document={{ fileId: 7, filename: 'p.jpg', kind: 'image', revisionName: 'E1 · 003' }} />)
    expect((screen.getByTestId('doc-image') as HTMLImageElement).src).toContain('/api/v1/parts/revision-files/7/inline')
    expect(screen.getByTestId('doc-header').textContent).toContain('p.jpg · E1 · 003')
  })

  it('renders children for 3d and never an iframe', () => {
    render(<DocumentPane document={{ fileId: 1, filename: 'm.stp', kind: '3d', revisionName: 'E1' }}><div>viewer-here</div></DocumentPane>)
    expect(screen.getByText('viewer-here')).toBeTruthy()
    expect(document.querySelector('iframe')).toBeNull()
  })

  it('shows the red mirror banner with the exact wording and opens the source', () => {
    const onOpen = vi.fn()
    render(<DocumentPane document={{ fileId: 1, filename: 'm.stp', kind: '3d', revisionName: 'E1' }}
      mirror={{ sourcePartId: 5, sourceNumber: '206.882.251', sourceName: 'Handle, height adjustment LH' }} onOpenPart={onOpen}><div /></DocumentPane>)
    const b = screen.getByTestId('mirror-banner')
    expect(b.textContent).toContain('Mirrored part. Showing 206.882.251 (Handle, height adjustment LH). Geometry is the mirror image, RPS and references differ.')
    expect(b.className).toContain('red')
    fireEvent.click(screen.getByText('Open source part'))
    expect(onOpen).toHaveBeenCalledWith(5)
  })

  it('placeholder when nothing to show', () => {
    render(<DocumentPane document={null} />)
    expect(screen.getByText(/No document to show/)).toBeTruthy()
  })

  it('shows a given placeholder instead of the default line', () => {
    render(<DocumentPane document={null} placeholder={<button>Open drawing</button>} />)
    expect(screen.getByText('Open drawing')).toBeTruthy()
    expect(screen.queryByText(/No document to show/)).toBeNull()
  })

  it('shows a close button that calls onClose when given', () => {
    const onClose = vi.fn()
    render(<DocumentPane document={{ fileId: 9, filename: 'p.png', kind: 'image', revisionName: 'E1' }} onClose={onClose} />)
    fireEvent.click(screen.getByTestId('doc-close'))
    expect(onClose).toHaveBeenCalled()
  })

  it('has no close button when onClose is not given', () => {
    render(<DocumentPane document={{ fileId: 9, filename: 'p.png', kind: 'image', revisionName: 'E1' }} />)
    expect(screen.queryByTestId('doc-close')).toBeNull()
  })
})
