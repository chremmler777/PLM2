import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { PlantFlag, plantCountry } from './PlantFlag'

describe('PlantFlag', () => {
  afterEach(cleanup)

  it('maps the plant to its country', () => {
    expect(plantCountry({ id: 1, name: 'Silao Mexico', code: 'SIL' })).toBe('MX')
    expect(plantCountry({ id: 2, name: 'USA Toccoa', code: 'usa-toccoa' })).toBe('US')
    expect(plantCountry({ id: 3, name: 'X', code: 'x', location: 'Toccoa, GA, USA' })).toBe('US')
    expect(plantCountry({ id: 4, name: 'Y', code: 'y', location: 'Nowhere' })).toBeNull()
  })

  it('shows one flag titled with the plant name', () => {
    render(<PlantFlag plant={{ id: 1, name: 'Silao Mexico', code: 'SIL' }} testId="f" />)
    const el = screen.getByTestId('f')
    expect(el.getAttribute('title')).toBe('Silao Mexico')
    expect(el.querySelectorAll('svg')).toHaveLength(1)
  })

  it('renders nothing for an unknown plant', () => {
    render(<PlantFlag plant={null} testId="f" />)
    expect(screen.queryByTestId('f')).toBeNull()
  })
})
