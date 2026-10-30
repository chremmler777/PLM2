import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { PlantFlags } from './PlantFlag'

describe('PlantFlags', () => {
  afterEach(cleanup)

  it('shows one flag with the plant name', () => {
    render(<PlantFlags countries={['MX']} testId="f" />)
    const el = screen.getByTestId('f')
    expect(el.getAttribute('title')).toBe('Silao (Mexico)')
    expect(el.querySelectorAll('svg')).toHaveLength(1)
  })

  it('shows both flags for a shared part', () => {
    render(<PlantFlags countries={['US', 'MX']} testId="f" />)
    const el = screen.getByTestId('f')
    expect(el.getAttribute('title')).toBe('Both plants: Toccoa (USA) + Silao (Mexico)')
    expect(el.querySelectorAll('svg')).toHaveLength(2)
  })

  it('renders nothing without a known country', () => {
    render(<PlantFlags countries={[]} testId="f" />)
    expect(screen.queryByTestId('f')).toBeNull()
    render(<PlantFlags countries={['XX']} testId="g" />)
    expect(screen.queryByTestId('g')).toBeNull()
  })
})
