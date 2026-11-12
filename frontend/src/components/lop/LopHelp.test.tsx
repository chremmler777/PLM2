import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import LopHelp from './LopHelp'

describe('LopHelp', () => {
  afterEach(cleanup)

  it('opens the instructions for the Project Manager from the LOP page', () => {
    render(<LopHelp />)
    expect(screen.queryByTestId('lop-help')).toBeNull()
    fireEvent.click(screen.getByTestId('lop-help-button'))
    const help = screen.getByTestId('lop-help')
    for (const word of ['Start meeting', 'Add from SEP', 'Pin', 'Discussed', 'Send minutes', 'two meetings in a row',
      'Done, please check', 'Book in PDB', 'Flag for planning', 'Send to PDB', 'one mail in the morning']) {
      expect(help.textContent).toContain(word)
    }
    // four pictures, each with a description for screen readers
    const shots = help.querySelectorAll('img')
    expect(shots).toHaveLength(4)
    shots.forEach((img) => expect(img.getAttribute('alt')).toBeTruthy())
  })
})
