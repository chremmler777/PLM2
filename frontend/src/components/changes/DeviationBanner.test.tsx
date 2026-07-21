import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import DeviationBanner from './DeviationBanner';
import ReasonDialog from './ReasonDialog';
import { changesApi } from '../../api/changes';

vi.mock('../../api/changes', () => ({
  changesApi: {
    listDeviations: vi.fn().mockResolvedValue([]),
    proposeDeviation: vi.fn().mockResolvedValue({ id: 1, status: 'pending' }),
    decideDeviation: vi.fn(),
  },
}));

function renderBanner() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DeviationBanner
        changeId={7}
        blockedTo="in_assessment"
        blockedReason="No impacted items added yet. An approved deviation is required to proceed."
        onRetry={() => {}}
        onClose={() => {}}
      />
    </QueryClientProvider>
  );
}

describe('DeviationBanner', () => {
  beforeEach(() => { vi.clearAllMocks(); });
  afterEach(() => { cleanup(); });

  it('shows the block reason', async () => {
    renderBanner();
    expect(await screen.findByText(/No impacted items/)).toBeDefined();
  });

  it('proposes a deviation with the entered reason', async () => {
    renderBanner();
    fireEvent.click(await screen.findByRole('button', { name: /request deviation/i }));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'PPT only' } });
    fireEvent.click(screen.getByRole('button', { name: /submit/i }));
    await waitFor(() =>
      expect(changesApi.proposeDeviation).toHaveBeenCalledWith(7, {
        to_status: 'in_assessment', reason: 'PPT only',
      })
    );
  });
});

describe('ReasonDialog', () => {
  afterEach(() => { cleanup(); });

  it('clears the textarea when reopened', () => {
    const { rerender } = render(
      <ReasonDialog open title="t" label="l" onSubmit={() => {}} onClose={() => {}} />
    );
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'stale text' } });
    rerender(<ReasonDialog open={false} title="t" label="l" onSubmit={() => {}} onClose={() => {}} />);
    rerender(<ReasonDialog open title="t" label="l" onSubmit={() => {}} onClose={() => {}} />);
    expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe('');
  });
});
