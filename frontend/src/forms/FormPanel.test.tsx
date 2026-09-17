import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import FormPanel from './FormPanel';

// The real module exports the axios client as default plus API_BASE_URL, which
// the export link is built from — the mock has to carry both or the named
// import blows up at module load.
vi.mock('../api/client', () => ({
  default: {
    get: vi.fn(async (url: string) => {
      if (url === '/v1/forms/instances/7') return { data: {
        id: 7, project_id: 1, key: 'lop', title: 'Open Points List (LOP)', version: 1, implements: 'F-DVS-CORP-010', cardinality: 'single',
        status: 'submitted', data: { header: {}, points: [] }, owner_id: 1, owner_name: 'Eng', updated_by_name: 'Eng', updated_at: '2026-09-03T10:00:00',
        submitted_by_name: 'Eng', submitted_at: '2026-09-03T10:00:00', signatures: {}, references: [], sep_items: [],
        definition: { key: 'lop', version: 1, title: 'Open Points List (LOP)', cardinality: 'single', gate_items: false, sep_items: [], signatures: [], required_for_submit: [],
          sections: [{ id: 'header', title: 'Project', kind: 'fields', fields: [{ id: 'project_no', label: 'Project No.', type: 'text' }] }] },
        events: [{ id: 1, user_id: 1, user_name: 'Eng', event: 'submitted', role: null, diff: null, created_at: '2026-09-03T10:00:00' }],
      } };
      if (url === '/v1/forms/instances/8') return { data: {
        id: 8, project_id: 1, key: 'lop', title: 'Open Points List (LOP)', version: 1, implements: null, cardinality: 'single',
        status: 'draft', data: { header: {} }, owner_id: 1, owner_name: 'Eng', updated_by_name: 'Eng', updated_at: '2026-09-03T10:00:00',
        submitted_by_name: null, submitted_at: null, signatures: {}, references: [], sep_items: [],
        definition: { key: 'lop', version: 1, title: 'Open Points List (LOP)', cardinality: 'single', gate_items: false, sep_items: [], signatures: [], required_for_submit: [],
          sections: [{ id: 'header', title: 'Project', kind: 'fields', fields: [{ id: 'project_no', label: 'Project No.', type: 'text' }] }] },
        events: [],
      } };
      if (url === '/v1/lessons/assignable-users') return { data: [{ id: 1, name: 'Eng' }] };
      throw new Error(url);
    }),
    post: vi.fn(async () => { throw { response: { status: 422, data: { detail: { message: 'Form is incomplete', missing: ['header.project_title', 'budget'] } } } }; }),
    patch: vi.fn(async () => ({ data: {} })),
  },
  API_BASE_URL: '',
}));

const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));
vi.mock('sonner', () => ({ toast: toastMocks }));

describe('FormPanel', () => {
  it('shows a submitted form read-only with reopen and export', async () => {
    const qc = new QueryClient();
    render(<QueryClientProvider client={qc}><FormPanel instanceId={7} onClose={() => {}} /></QueryClientProvider>);
    await waitFor(() => expect(screen.getByText('Open Points List (LOP)')).toBeTruthy());
    expect(screen.getByText('submitted')).toBeTruthy();
    expect(screen.getByRole('button', { name: /reopen/i })).toBeTruthy();
    expect(screen.getByRole('link', { name: /export pdf/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^save$/i })).toBeNull();
    cleanup();
  });

  it('names the still-empty fields when submit comes back incomplete', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={qc}><FormPanel instanceId={8} onClose={() => {}} /></QueryClientProvider>);
    const submit = await screen.findByRole('button', { name: /^submit$/i });
    fireEvent.click(submit);
    await waitFor(() => expect(toastMocks.error).toHaveBeenCalledWith(
      'Form is incomplete: header.project_title, budget'));
    cleanup();
  });
});
