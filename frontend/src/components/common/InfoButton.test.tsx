import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import InfoButton from './InfoButton';

describe('InfoButton', () => {
  it('toggles its explanation and closes on Escape', () => {
    render(<InfoButton label="What does urgent do?"><p>Faster, not shorter</p></InfoButton>);
    const btn = screen.getByRole('button', { name: 'What does urgent do?' });
    expect(screen.queryByText('Faster, not shorter')).toBeNull();
    fireEvent.click(btn);
    expect(btn.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByText('Faster, not shorter')).toBeTruthy();
    fireEvent.keyDown(btn, { key: 'Escape' });
    expect(screen.queryByText('Faster, not shorter')).toBeNull();
  });
});
