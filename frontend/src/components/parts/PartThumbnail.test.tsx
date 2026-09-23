import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import PartThumbnail from './PartThumbnail'

vi.mock('../../api/client', () => ({ default: {}, API_BASE_URL: '/plm2/api' }))

describe('PartThumbnail', () => {
  afterEach(cleanup)

  it('shows the image under the app API base, lazy, with the part name as alt text', () => {
    render(<PartThumbnail url="/api/v1/parts/5/thumbnail?v=17" name="ISOFIX Cover" testId="t" />)
    const img = screen.getByAltText('ISOFIX Cover') as HTMLImageElement
    expect(img.getAttribute('src')).toBe('/plm2/api/v1/parts/5/thumbnail?v=17')
    expect(img.getAttribute('loading')).toBe('lazy')
    expect(img.className).toContain('object-contain')
    expect(screen.queryByTestId('t-placeholder')).toBeNull()
    expect(screen.getByTestId('t').className).toContain('w-10')
  })

  it('shows the placeholder when there is no thumbnail', () => {
    render(<PartThumbnail url={null} name="ISOFIX Cover" size="lg" testId="t" />)
    expect(screen.queryByRole('img', { name: 'ISOFIX Cover' })).toBeNull()
    expect(screen.getByTestId('t-placeholder')).toBeTruthy()
    expect(screen.getByTestId('t').className).toContain('w-24')
  })

  it('falls back to the placeholder when the image fails to load', () => {
    render(<PartThumbnail url="/api/v1/parts/5/thumbnail?v=1" name="ISOFIX Cover" testId="t" />)
    fireEvent.error(screen.getByAltText('ISOFIX Cover'))
    expect(screen.queryByAltText('ISOFIX Cover')).toBeNull()
    expect(screen.getByTestId('t-placeholder')).toBeTruthy()
  })
})
