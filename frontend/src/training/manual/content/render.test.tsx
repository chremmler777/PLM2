import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { CHAPTERS } from '../chapters'
import { renderBlocks } from './render'

afterEach(cleanup)

describe('renderBlocks', () => {
  it('renders a screenshot slot as a named frame until its picture exists', () => {
    render(<>{renderBlocks([{ shot: 'pm-deviations', alt: 'The deviations list.' }])}</>)
    const frame = screen.getByTestId('shot-pm-deviations')
    expect(frame.textContent).toContain('Screenshot follows')
    expect(frame.textContent).toContain('pm-deviations')
    expect(frame.textContent).toContain('The deviations list.')
    expect(frame.querySelector('img')).toBeNull()
  })

  it('renders the picture once the slot is available', () => {
    render(<>{renderBlocks([{ shot: 'pm-deviations', alt: 'The deviations list.' }], new Set(['pm-deviations']))}</>)
    expect(screen.queryByTestId('shot-pm-deviations')).toBeNull()
    expect(screen.getByAltText('The deviations list.').getAttribute('src')).toMatch(/manual\/pm-deviations\.png$/)
  })

  it('shows written content in the manual chapters, no pending stub', () => {
    const pm = CHAPTERS.find((c) => c.id === 'pm')!
    render(<>{pm.sections.map((s) => <div key={s.id}>{s.body}</div>)}</>)
    expect(screen.queryByTestId('manual-pending')).toBeNull()
    expect(screen.getAllByText(/Deviations from the baseline/).length).toBeGreaterThan(0)
  })
})
