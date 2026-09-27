import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import PlantNotInUseNote from './PlantNotInUseNote'

describe('PlantNotInUseNote', () => {
  afterEach(cleanup)

  it('shows one quiet note when Silao is among the plants', () => {
    render(<PlantNotInUseNote plants={[{ code: 'USA' }, { code: 'SIL', local_currency: 'MXN' }]} />)
    const notes = screen.getAllByTestId('plant-not-in-use')
    expect(notes).toHaveLength(1)
    expect(notes[0].getAttribute('role')).toBe('note')
    expect(notes[0].textContent).toBe('Mexico (Silao) is not in use yet. PLM runs for the US plant only for now; '
      + 'access for Mexico will be role based later.')
  })

  it('renders nothing for the US plant alone', () => {
    const { container } = render(<PlantNotInUseNote plants={[{ code: 'USA', location: 'US' }]} />)
    expect(container.innerHTML).toBe('')
  })
})
