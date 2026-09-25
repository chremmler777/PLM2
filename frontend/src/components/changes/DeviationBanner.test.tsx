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

function renderBanner(seq = 1) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DeviationBanner
        changeId={7}
        blockedTo="in_assessment"
        blockedReason="No impacted items added yet. An approved deviation is required to proceed."
        seq={seq}
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

  it('scrolls itself into view and takes focus when a block is reported', async () => {
    const targets: Element[] = [];
    const scroll = vi.fn(function (this: Element) { targets.push(this); });
    const orig = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scroll;
    try {
      renderBanner();
      const banner = await screen.findByTestId('deviation-banner');
      expect(scroll).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
      expect(targets[0]).toBe(banner);
      expect(document.activeElement).toBe(banner);
    } finally {
      HTMLElement.prototype.scrollIntoView = orig;
    }
  });

  it('scrolls into view again when an identical block is reported a second time (seq bumped)', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const scroll = vi.fn();
    const orig = HTMLElement.prototype.scrollIntoView;
    HTMLElement.prototype.scrollIntoView = scroll;
    try {
      const { rerender } = render(
        <QueryClientProvider client={qc}>
          <DeviationBanner changeId={7} blockedTo="in_assessment" blockedReason="Same reason"
            seq={1} onRetry={() => {}} onClose={() => {}} />
        </QueryClientProvider>
      );
      await screen.findByTestId('deviation-banner');
      expect(scroll).toHaveBeenCalledTimes(1);

      // Same blockedTo/blockedReason, but a new block was reported: seq bumps.
      rerender(
        <QueryClientProvider client={qc}>
          <DeviationBanner changeId={7} blockedTo="in_assessment" blockedReason="Same reason"
            seq={2} onRetry={() => {}} onClose={() => {}} />
        </QueryClientProvider>
      );
      expect(scroll).toHaveBeenCalledTimes(2);
    } finally {
      HTMLElement.prototype.scrollIntoView = orig;
    }
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
