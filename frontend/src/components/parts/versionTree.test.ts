import { describe, expect, it } from 'vitest';
import { buildVersionTree, fileSlot, versionState } from './versionTree';

const rev = (id: number, name: string, extra: Partial<Record<string, unknown>> = {}) => ({
  id, revision_name: name, phase: 'review' as const, status: 'approved', customer_index: null as string | null,
  parent_revision_id: null as number | null, summary: null as string | null,
  customer_received_at: null as string | null, created_at: `2026-09-0${id % 9 + 1}T00:00:00`, ...extra,
});
const file = (id: number, revision_id: number, filename: string, file_type: string, cad_format: string | null = null) => ({
  id, revision_id, filename, file_type, cad_format, mime_type: '', file_size: 1, has_viewer: false, uploaded_at: '',
});

describe('fileSlot', () => {
  it('sorts files into native 3D, STEP and drawing', () => {
    expect(fileSlot(file(1, 1, 'a.CATPart', 'cad', 'catia'))).toBe('native');
    expect(fileSlot(file(1, 1, 'a.stp', 'cad', 'step'))).toBe('step');
    expect(fileSlot(file(1, 1, 'a.pdf', 'drawing'))).toBe('drawing');
    expect(fileSlot(file(1, 1, 'a.pdf', 'document'))).toBeNull();
    expect(fileSlot(file(1, 1, 'a.stl', 'cad', 'stl'))).toBeNull();
  });
});

describe('buildVersionTree completeness', () => {
  // Belt exit cover: E1 · 003 full set, E2 · 005 CATPart only
  const e1 = rev(1, 'E1', { customer_index: '003' });
  const e2 = rev(2, 'E2', { customer_index: '005', status: 'in_review' });
  const e11 = rev(3, 'E1.1', { parent_revision_id: 1, status: 'draft' });
  const files = [
    file(10, 1, 'PCA_003.CATPart', 'cad', 'catia'), file(11, 1, 'PCA_003.stp', 'cad', 'step'),
    file(12, 1, 'DRW_001.pdf', 'drawing'), file(20, 2, 'KPR_005.CATPart', 'cad', 'catia'),
    file(30, 3, 'HANDLE_fz.stp', 'cad', 'step'),
  ];
  const tree = buildVersionTree([e1, e2, e11], files, { activeId: 1, pending: new Map([[2, 'pending triage']]) });

  it('lists newest customer version first with its iterations nested', () => {
    expect(tree.map((n) => n.rev.revision_name)).toEqual(['E2', 'E1']);
    expect(tree[1].children.map((n) => n.rev.revision_name)).toEqual(['E1.1']);
  });

  it('marks a slot the version holds as here', () => {
    expect(tree[1].slots.native.kind).toBe('here');
    expect(tree[1].slots.drawing.kind).toBe('here');
  });

  it('marks a slot only an older version holds as stale, naming the file and version', () => {
    const d = tree[0].slots.drawing;
    expect(d.kind).toBe('stale');
    expect(d.kind === 'stale' && d.from.revision_name).toBe('E1');
    expect(d.kind === 'stale' && d.file.filename).toBe('DRW_001.pdf');
    expect(tree[0].slots.step.kind).toBe('stale');
    expect(tree[0].slots.native.kind).toBe('here');
  });

  it('marks a slot no version holds as missing', () => {
    const only = buildVersionTree([e1], [file(10, 1, 'a.CATPart', 'cad', 'catia')], { activeId: 1 });
    expect(only[0].slots.drawing.kind).toBe('missing');
  });

  it('lets an iteration inherit what it does not hold, never stale', () => {
    const it11 = tree[1].children[0];
    expect(it11.slots.step.kind).toBe('here');
    expect(it11.slots.drawing.kind).toBe('inherited');
    expect(it11.slots.native.kind).toBe('inherited');
  });

  it('carries the iteration gap through to missing when the parent lacks it too', () => {
    const t = buildVersionTree([e1, e11], [file(30, 3, 'x.stp', 'cad', 'step')], { activeId: 1 });
    expect(t[0].children[0].slots.drawing.kind).toBe('missing');
  });

  it('ignores a rejected older version as a source', () => {
    const t = buildVersionTree(
      [rev(1, 'E1', { status: 'rejected' }), rev(2, 'E2')],
      [file(12, 1, 'DRW.pdf', 'drawing')], { activeId: 2 });
    expect(t[0].slots.drawing.kind).toBe('missing');
  });

  it('picks the worst gap as the headline issue', () => {
    expect(tree[0].issue).toMatchObject({ slot: 'step', kind: 'stale' });
    const t = buildVersionTree([e1], [file(10, 1, 'a.CATPart', 'cad', 'catia')], { activeId: 1 });
    expect(t[0].issue).toMatchObject({ kind: 'missing' });
    expect(tree[1].issue).toBeNull();
  });
});

describe('versionState', () => {
  const opts = { activeId: 1, pending: new Map([[2, 'pending triage']]) };
  it('names the state of each version in plain words', () => {
    expect(versionState(rev(1, 'E1'), opts)).toMatchObject({ label: 'active', tone: 'active' });
    expect(versionState(rev(2, 'E2', { status: 'in_review' }), opts)).toMatchObject({ label: 'pending triage', tone: 'waiting' });
    expect(versionState(rev(5, 'E0'), { ...opts, olderThanActive: true })).toMatchObject({ label: 'superseded', tone: 'dead' });
    expect(versionState(rev(3, 'E1.1', { parent_revision_id: 1, status: 'draft' }), opts)).toMatchObject({ label: 'open iteration', tone: 'open' });
    expect(versionState(rev(3, 'E1.1', { parent_revision_id: 1, status: 'approved' }), opts)).toMatchObject({ label: 'adopted by customer' });
    expect(versionState(rev(3, 'E1.1', { parent_revision_id: 1, status: 'rejected' }), opts)).toMatchObject({ label: 'rejected', tone: 'dead' });
    expect(versionState(rev(6, 'E3', { status: 'frozen' }), opts)).toMatchObject({ label: 'frozen' });
  });
});
