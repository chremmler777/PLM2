/**
 * Dotted connector segments joining the two rows of a mirror pair in the
 * items list. Pure, measurement-free: works off the visible row order only,
 * so it holds up in jsdom and at any row height.
 */
import type { StructureArticle } from '../../hooks/queries/useProjectStructure';

export const MIRROR_LANE_WIDTH = 6;
export const MIRROR_MAX_LANES = 3;

export interface MirrorSegment {
  lane: number;
  kind: 'start' | 'middle' | 'end';
  /** Stable id shared by both rows of a pair, e.g. "5-12". */
  pairId: string;
}

interface Pair {
  pairId: string;
  start: number;
  end: number;
}

/**
 * Maps each visible row id that takes part in a mirror pair to the
 * connector segments drawn in its gutter cell. A pair whose partner is not
 * in `order` is skipped entirely. Lanes are assigned greedily so
 * overlapping pairs land in different lanes, up to MIRROR_MAX_LANES; beyond
 * that pairs reuse the last lane.
 */
export function mirrorConnectors(
  order: number[],
  articles: StructureArticle[],
): Map<number, MirrorSegment[]> {
  const indexOf = new Map<number, number>();
  order.forEach((id, i) => indexOf.set(id, i));

  const pairs: Pair[] = [];
  const seen = new Set<string>();
  for (const article of articles) {
    if (!article.mirror_of) continue;
    const otherId = article.mirror_of.part_id;
    const pairId = [article.part_id, otherId].sort((a, b) => a - b).join('-');
    if (seen.has(pairId)) continue;
    seen.add(pairId);
    const i1 = indexOf.get(article.part_id);
    const i2 = indexOf.get(otherId);
    if (i1 === undefined || i2 === undefined || i1 === i2) continue;
    pairs.push({ pairId, start: Math.min(i1, i2), end: Math.max(i1, i2) });
  }
  pairs.sort((a, b) => a.start - b.start);

  // laneEnds[lane] = end index of the last pair placed in that lane.
  const laneEnds: number[] = [];
  const result = new Map<number, MirrorSegment[]>();
  const addSegment = (rowId: number, segment: MirrorSegment) => {
    const list = result.get(rowId) ?? [];
    list.push(segment);
    result.set(rowId, list);
  };

  for (const pair of pairs) {
    let lane = laneEnds.findIndex((end) => end < pair.start);
    if (lane === -1) {
      if (laneEnds.length < MIRROR_MAX_LANES) {
        lane = laneEnds.length;
        laneEnds.push(pair.end);
      } else {
        lane = MIRROR_MAX_LANES - 1;
        laneEnds[lane] = pair.end;
      }
    } else {
      laneEnds[lane] = pair.end;
    }

    addSegment(order[pair.start], { lane, kind: 'start', pairId: pair.pairId });
    addSegment(order[pair.end], { lane, kind: 'end', pairId: pair.pairId });
    for (let i = pair.start + 1; i < pair.end; i++) {
      addSegment(order[i], { lane, kind: 'middle', pairId: pair.pairId });
    }
  }

  return result;
}

/** Gutter width in px: zero when no pair is visible, else covers the lanes actually used. */
export function mirrorGutterWidth(connectors: Map<number, MirrorSegment[]>): number {
  let maxLane = -1;
  connectors.forEach((segments) => segments.forEach((s) => { if (s.lane > maxLane) maxLane = s.lane; }));
  return maxLane === -1 ? 0 : (maxLane + 1) * MIRROR_LANE_WIDTH;
}
