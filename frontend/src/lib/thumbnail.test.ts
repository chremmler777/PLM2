import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient } from '@tanstack/react-query'

const clientMocks = vi.hoisted(() => ({ put: vi.fn() }))
vi.mock('../api/client', () => ({ default: clientMocks, API_BASE_URL: '/plm2/api' }))

import { claimAutoCapture, invalidateThumbnailQueries, resetAutoCaptureForTests, thumbnailSrc, uploadThumbnail } from './thumbnail'

describe('thumbnail helpers', () => {
  beforeEach(() => { clientMocks.put.mockReset(); resetAutoCaptureForTests() })

  it('maps the server url onto the app API base', () => {
    expect(thumbnailSrc('/api/v1/parts/5/thumbnail?v=3')).toBe('/plm2/api/v1/parts/5/thumbnail?v=3')
    expect(thumbnailSrc('https://x/y.png')).toBe('https://x/y.png')
    expect(thumbnailSrc(null)).toBeNull()
  })

  it('uploads the image as multipart file', async () => {
    clientMocks.put.mockResolvedValue({ data: { id: 5 } })
    await uploadThumbnail(5, new Blob(['x'], { type: 'image/webp' }))
    const [url, body] = clientMocks.put.mock.calls[0]
    expect(url).toBe('/v1/parts/5/thumbnail')
    const file = (body as FormData).get('file') as File
    expect(file.name).toBe('thumbnail-5.webp')
  })

  it('claims the automatic capture once per part', () => {
    expect(claimAutoCapture(5)).toBe(true)
    expect(claimAutoCapture(5)).toBe(false)
    expect(claimAutoCapture(6)).toBe(true)
  })

  it('invalidates parts lists, structures and the part detail', () => {
    const qc = new QueryClient()
    const spy = vi.spyOn(qc, 'invalidateQueries')
    invalidateThumbnailQueries(qc, 5)
    expect(spy).toHaveBeenCalledWith({ queryKey: ['parts'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['project-structure'] })
    const predicate = (spy.mock.calls[2][0] as unknown as { predicate: (q: { queryKey: unknown[] }) => boolean }).predicate
    expect(predicate({ queryKey: ['part', '5'] })).toBe(true)
    expect(predicate({ queryKey: ['part', 6] })).toBe(false)
  })
})
