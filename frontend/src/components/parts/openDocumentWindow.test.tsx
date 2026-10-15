import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import type { ReactElement } from 'react'
import { documentInlineUrl, documentWindowName, openDocumentWindow, opensInWindow } from './openDocumentWindow'

vi.mock('../../api/client', () => ({ default: {}, API_BASE_URL: '/api' }))
const toastMocks = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }))
vi.mock('sonner', () => ({ toast: toastMocks }))

describe('openDocumentWindow', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); toastMocks.error.mockReset() })

  it('builds the revision file inline url, or takes the given override', () => {
    expect(documentInlineUrl({ fileId: 7, filename: 'd.pdf' })).toBe('/api/v1/parts/revision-files/7/inline')
    expect(documentInlineUrl({ fileId: 9, filename: 's.pdf', inlineUrl: '/api/v1/parts/3/dfm/files/9/inline' }))
      .toBe('/api/v1/parts/3/dfm/files/9/inline')
  })

  it('names one window per file, DFM files in their own name space', () => {
    expect(documentWindowName({ fileId: 7, filename: 'd.pdf' })).toBe('plm2-doc-7')
    expect(documentWindowName({ fileId: 7, filename: 'd.pdf', inlineUrl: '/x' })).toBe('plm2-doc-dfm-7')
  })

  it('opens a named popup and focuses it, so a second open reuses the window', () => {
    const focus = vi.fn()
    const open = vi.spyOn(window, 'open').mockReturnValue({ focus } as unknown as Window)
    expect(openDocumentWindow({ fileId: 7, filename: 'd.pdf' })).toBe(true)
    openDocumentWindow({ fileId: 7, filename: 'd.pdf' })
    expect(open).toHaveBeenNthCalledWith(1, '/api/v1/parts/revision-files/7/inline', 'plm2-doc-7', 'popup,width=1200,height=900')
    expect(open).toHaveBeenNthCalledWith(2, '/api/v1/parts/revision-files/7/inline', 'plm2-doc-7', 'popup,width=1200,height=900')
    expect(focus).toHaveBeenCalledTimes(2)
    expect(toastMocks.error).not.toHaveBeenCalled()
  })

  it('when the popup is blocked, toasts with a plain link to the file', () => {
    vi.spyOn(window, 'open').mockReturnValue(null)
    expect(openDocumentWindow({ fileId: 7, filename: 'd.pdf' })).toBe(false)
    expect(toastMocks.error).toHaveBeenCalledWith('The browser blocked the new window', expect.anything())
    const { description } = toastMocks.error.mock.calls[0][1] as { description: ReactElement }
    render(description)
    const link = screen.getByText('Open d.pdf in a new tab') as HTMLAnchorElement
    expect(link.getAttribute('href')).toBe('/api/v1/parts/revision-files/7/inline')
    expect(link.getAttribute('target')).toBe('_blank')
  })

  it('pops up PDFs and pictures filed as drawings; other pictures stay in the pane', () => {
    expect(opensInWindow({ filename: 'd.pdf', mime_type: 'application/pdf', file_type: 'drawing' })).toBe(true)
    expect(opensInWindow({ filename: 'spec.PDF', mime_type: 'application/octet-stream', file_type: 'document' })).toBe(true)
    expect(opensInWindow({ filename: 'scan.png', mime_type: 'image/png', file_type: 'drawing' })).toBe(true)
    expect(opensInWindow({ filename: 'photo.jpg', mime_type: 'image/jpeg', file_type: 'document' })).toBe(false)
    expect(opensInWindow({ filename: 'm.stp', mime_type: 'application/step', file_type: 'cad' })).toBe(false)
  })
})
