/**
 * Grouping rules for the revision timeline: majors (E1, E2, 1, 2 …) with
 * their internal proposals (E1.1, 1.1 …) underneath.
 */
export interface Revision {
  id: number;
  revision_name: string;
  phase: 'review' | 'official';
  status: string;
  summary?: string | null;
  parent_revision_id?: number | null;
  source: 'customer' | 'internal';
  customer_index?: string | null;
  customer_received_at?: string | null;
  part_phase_at_receipt: string;
  created_at: string;
}

export function parseRevisionName(name: string): { official: boolean; major: number; minor: number | null } {
  const m = /^(E?)(\d+)(?:\.(\d+))?$/.exec(name);
  if (!m) return { official: false, major: 0, minor: null };
  return { official: m[1] === '', major: Number(m[2]), minor: m[3] ? Number(m[3]) : null };
}

/** Official majors first, newest first; minors ascending. */
export function groupByMajor<
  T extends Pick<Revision, 'id' | 'revision_name' | 'phase' | 'status' | 'parent_revision_id' | 'customer_index'>
>(revisions: T[]): { major: T; minors: T[] }[] {
  const majors = revisions.filter((r) => !r.parent_revision_id);
  return majors
    .map((major) => ({
      major,
      minors: revisions
        .filter((r) => r.parent_revision_id === major.id)
        .sort((a, b) => (parseRevisionName(a.revision_name).minor ?? 0) - (parseRevisionName(b.revision_name).minor ?? 0)),
    }))
    .sort((a, b) => {
      const pa = parseRevisionName(a.major.revision_name);
      const pb = parseRevisionName(b.major.revision_name);
      if (pa.official !== pb.official) return pa.official ? -1 : 1;
      return pb.major - pa.major;
    });
}
