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
      'Done, please check', 'Book in PDB']) {
      expect(help.textContent).toContain(word)
    }
  })
})
