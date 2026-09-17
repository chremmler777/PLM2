import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, cleanup } from '@testing-library/react';
import FormRenderer from './FormRenderer';
import type { FormDefinitionBody } from './types';

const body: FormDefinitionBody = {
  key: 'all', version: 1, title: 'All', cardinality: 'single', gate_items: false, sep_items: [], signatures: [], required_for_submit: [],
  sections: [
    { id: 'h', title: 'Header', kind: 'fields', fields: [
      { id: 't', label: 'Text', type: 'text' }, { id: 'm', label: 'Multi', type: 'multiline' },
      { id: 'n', label: 'Num', type: 'number' }, { id: 'd', label: 'Date', type: 'date' },
      { id: 'b', label: 'Check', type: 'checkbox' }, { id: 'c', label: 'Choice', type: 'choice', options: ['a', 'b'] },
      { id: 'mc', label: 'Multi choice', type: 'multichoice', options: ['x', 'y'] },
      { id: 'u', label: 'User', type: 'user' }, { id: 'dbl', label: 'Double', type: 'computed', expr: 'n * 2', help: 'twice n' },
    ] },
    { id: 'rows', title: 'Rows', kind: 'table', columns: [
      { id: 'q', label: 'Q', type: 'number' }, { id: 'r', label: 'R', type: 'computed', expr: 'q * 2', help: 'twice q' },
    ], footer: [{ label: 'Sum R', expr: 'sum(r)' }] },
  ],
};

describe('FormRenderer', () => {
  it('renders every field type, recomputes on change, adds rows', () => {
    const onChange = vi.fn();
    render(<FormRenderer body={body} data={{ h: { n: 2 }, rows: [] }} onChange={onChange} users={[{ id: 1, name: 'Eng' }]} />);
    expect(screen.getByLabelText('Text')).toBeTruthy();
    expect(screen.getByLabelText('Multi')).toBeTruthy();
    expect(screen.getByLabelText('Date')).toBeTruthy();
    expect(screen.getByLabelText('Check')).toBeTruthy();
    expect(screen.getByLabelText('Choice')).toBeTruthy();
    expect(screen.getByLabelText('User')).toBeTruthy();
    expect(screen.getByText('twice n')).toBeTruthy();
    expect(screen.getByText('4')).toBeTruthy(); // computed double shown
    expect(screen.getByText('R = twice q')).toBeTruthy(); // column legend
    fireEvent.change(screen.getByLabelText('Num'), { target: { value: '5' } });
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ h: expect.objectContaining({ n: 5, dbl: 10 }) }));
    fireEvent.click(screen.getByRole('button', { name: /add row/i }));
    const last = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect((last.rows as unknown[]).length).toBe(1);
    cleanup();
  });

  it('read-only renders no inputs or add-row', () => {
    render(<FormRenderer body={body} data={{ h: { t: 'hello' }, rows: [{ q: 1 }] }} onChange={() => {}} readOnly users={[]} />);
    expect(screen.queryByRole('button', { name: /add row/i })).toBeNull();
    expect(screen.getByText('hello')).toBeTruthy();
    cleanup();
  });
});
