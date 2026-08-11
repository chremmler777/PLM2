import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { UploadedBy } from './UploadedBy'

const shown = (at: string) => new Date(at).toLocaleDateString()

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

  it('renders nothing when there is no provenance at all', () => {
    const { container } = render(<UploadedBy />)
    expect(container.firstChild).toBeNull()
  })
})
