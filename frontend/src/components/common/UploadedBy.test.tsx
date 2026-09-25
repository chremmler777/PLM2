import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { UploadedBy } from './UploadedBy'
import { formatDate } from '../../lib/format'

// Always dd.mm.yyyy, never the browser locale.
const shown = (at: string) => formatDate(at)

describe('UploadedBy', () => {
  afterEach(cleanup)

  it('names the uploader and the date', () => {
    render(<UploadedBy name="Eva Eng" at="2026-07-01T00:00:00" />)
    expect(screen.getByTestId('uploaded-by').textContent)
      .toBe(`Eva Eng · ${shown('2026-07-01T00:00:00')}`)
  })

  it('falls back to the date alone when the uploader is unknown', () => {
    render(<UploadedBy at="2026-07-01T00:00:00" />)
    const line = screen.getByTestId('uploaded-by')
    expect(line.textContent).toBe(shown('2026-07-01T00:00:00'))
    expect(line.textContent).not.toContain('·')
  })

  it('writes the day as dd.mm.yyyy', () => {
    render(<UploadedBy name="Eva Eng" at="2026-07-01T12:00:00" />)
    expect(screen.getByTestId('uploaded-by').textContent).toMatch(/^Eva Eng · \d{2}\.\d{2}\.2026$/)
  })

  it('renders nothing when there is no provenance at all', () => {
    const { container } = render(<UploadedBy />)
    expect(container.firstChild).toBeNull()
  })
})
