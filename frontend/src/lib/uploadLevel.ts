/** Pure helpers for the upload dialog: which level to preselect and what
 *  the next revision would be called. Detection prefills, the user decides. */
export type UploadLevel = 'attach' | 'major' | 'proposal';

export interface ParsedRow {
  filename: string;
  customer_part_number: string | null;
  variant: string | null;
  kind: string | null;
  kind_label: string | null;
  model_type: string | null;
  customer_index: string | null;
  release: string | null;
  dated: string | null;
}

export function detectedIndex(rows: ParsedRow[]): { index: string | null; mixed: boolean } {
  const found = Array.from(new Set(rows.map((r) => r.customer_index).filter((x): x is string => !!x)));
  if (found.length === 0) return { index: null, mixed: false };
  if (found.length > 1) return { index: null, mixed: true };
  return { index: found[0], mixed: false };
}

export function defaultLevel(detected: string | null, current: string | null | undefined): UploadLevel {
  if (!detected) return 'attach';
  if ((current ?? '').trim().toLowerCase() === detected.trim().toLowerCase()) return 'attach';
  return 'major';
}

const CAD = ['.step', '.stp', '.iges', '.igs', '.stl', '.jt', '.catpart', '.catproduct'];
const DRAWING = ['.pdf', '.dxf', '.dwg'];
const PICTURE = ['.png', '.jpg', '.jpeg', '.gif', '.webp'];

export function inferFileType(filename: string): 'cad' | 'drawing' | 'picture' | 'document' {
  const lower = filename.toLowerCase();
  const ext = lower.includes('.') ? lower.slice(lower.lastIndexOf('.')) : '';
  if (CAD.includes(ext)) return 'cad';
  if (DRAWING.includes(ext)) return 'drawing';
  if (PICTURE.includes(ext)) return 'picture';
  return 'document';
}

const majors = (names: string[]) => names.filter((n) => !n.includes('.'));

export function nextMajorName(revisionNames: string[], statement: 'review' | 'official'): string {
  const ms = majors(revisionNames);
  if (statement === 'review') {
    const n = Math.max(0, ...ms.filter((m) => m.startsWith('E')).map((m) => parseInt(m.slice(1), 10) || 0));
    return `E${n + 1}`;
  }
  const n = Math.max(0, ...ms.filter((m) => !m.startsWith('E')).map((m) => parseInt(m, 10) || 0));
  return String(n + 1);
}

export function nextProposalName(revisionNames: string[], parent: string): string {
  const minors = revisionNames
    .filter((n) => n.startsWith(`${parent}.`))
    .map((n) => parseInt(n.slice(parent.length + 1), 10) || 0);
  return `${parent}.${Math.max(0, ...minors) + 1}`;
}
