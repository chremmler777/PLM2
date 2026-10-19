import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import VersionNav, { type NavFile } from './VersionNav';

const revs = [
  { id: 1, revision_name: 'E1', customer_index: '003', phase: 'review' as const, status: 'approved',
    parent_revision_id: null, summary: 'Awarded quote baseline (RFQ2 REV8).', created_at: '2026-09-02T00:00:00' },
  { id: 2, revision_name: 'E2', customer_index: '005', phase: 'review' as const, status: 'in_review', intake_pending: true,
    parent_revision_id: null, summary: 'Customer review data, index 005\nsecond line', customer_received_at: '2026-10-15', created_at: '2026-10-19T00:00:00' },
  { id: 3, revision_name: 'E1.1', customer_index: null, phase: 'review' as const, status: 'draft',
    parent_revision_id: 1, summary: 'Toolmaker data, awaiting customer confirmation', created_at: '2026-10-19T00:00:00' },
];
const f = (id: number, revision_id: number, filename: string, file_type: string, cad_format: string | null, has_viewer = false): NavFile =>
  ({ id, revision_id, filename, file_type, cad_format, has_viewer, mime_type: file_type === 'drawing' ? 'application/pdf' : '' });
const files = [
  f(10, 1, 'PCA_003.CATPart', 'cad', 'catia'), f(11, 1, 'PCA_003.stp', 'cad', 'step', true),
  f(12, 1, 'DRW_001.pdf', 'drawing', null), f(20, 2, 'KPR_005.CATPart', 'cad', 'catia'),
];

function mount(over: Partial<React.ComponentProps<typeof VersionNav>> = {}) {
  const props = {
    revisions: revs, files, activeId: 1, selectedRevisionId: 1, viewingFileId: null,
    onSelectRevision: vi.fn(), onFile: vi.fn(), onNewIteration: vi.fn(), ...over,
  };
  render(<VersionNav {...props} />);
  return props;
}

describe('VersionNav', () => {
  beforeEach(() => { try { window.localStorage.clear(); } catch { /* none */ } });
  afterEach(cleanup);

  it('shows each version with its state and the first line of its summary', () => {
    mount();
    expect(screen.getByTestId('nav-state-1').textContent).toBe('active');
    expect(screen.getByTestId('nav-state-2').textContent).toBe('waiting for triage');
    expect(screen.getByTestId('nav-state-3').textContent).toBe('open iteration');
    expect(screen.getByText('Customer review data, index 005')).toBeTruthy();
    expect(screen.queryByText(/second line/)).toBeNull();
  });

  it('flags the drawing a new version did not update, naming the old file', () => {
    mount();
    const row = screen.getByTestId('nav-rev-2');
    const drawing = row.querySelector('[data-testid="slot-drawing"]')!;
    expect(drawing.getAttribute('data-kind')).toBe('stale');
    expect(drawing.getAttribute('title')).toBe('drawing not updated: still DRW_001.pdf from E1 · 003');
  });

  it('sends a picked file and its version up', () => {
    const p = mount();
    fireEvent.click(screen.getByTestId('nav-file-11'));
    expect(p.onSelectRevision).toHaveBeenCalledWith(1);
    expect(p.onFile).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }));
  });

  it('expands and collapses a version', () => {
    mount();
    expect(screen.getByTestId('nav-file-20')).toBeTruthy(); // waiting: open by default
    const toggle = screen.getByTestId('nav-rev-2').parentElement!.querySelector('button[aria-label="Collapse"]')!;
    fireEvent.click(toggle);
    expect(screen.queryByTestId('nav-file-20')).toBeNull();
  });

  it('offers a new iteration on the selected customer version only', () => {
    const p = mount();
    expect(screen.queryByTestId('nav-new-iteration-2')).toBeNull();
    fireEvent.click(screen.getByTestId('nav-new-iteration-1'));
    expect(p.onNewIteration).toHaveBeenCalledWith(1);
  });

  it('folds into a strip that counts versions with gaps, and remembers it', () => {
    mount();
    fireEvent.click(screen.getByLabelText('Hide versions'));
    expect(screen.getByTestId('version-nav').getAttribute('data-collapsed')).toBe('true');
    expect(screen.getByTitle('1 version with missing or outdated files')).toBeTruthy();
    cleanup();
    mount();
    expect(screen.getByTestId('version-nav').getAttribute('data-collapsed')).toBe('true');
  });
});

describe('shortName', () => {
  it('keeps the distinguishing end of long Brose names', async () => {
    const { shortName } = await import('./versionTree');
    const a = shortName('206_883_607____PCA_TM__003_____BELT_EXIT_COVER____B-RELEASE___20260528.CATPart');
    const b = shortName('206_883_607____PCA_TM__003_____BELT_EXIT_COVER____B-RELEASE___20260528.CATPart.stp');
    expect(a).not.toBe(b);
    expect(a.endsWith('.CATPart')).toBe(true);
    expect(a.length).toBeLessThanOrEqual(32);
    expect(a.startsWith('PCA_TM_003')).toBe(true);
    expect(shortName('short.pdf')).toBe('short.pdf');
  });
});
