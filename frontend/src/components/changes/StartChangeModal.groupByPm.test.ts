import { describe, expect, it } from 'vitest';
import { groupByPm } from './StartChangeModal';

const p = (id: number, code: string) => ({ id, code, name: `P${id}` });

describe('groupByPm (Start change project picker order)', () => {
  it('puts my projects first, other PMs next, no PM last', () => {
    const groups = groupByPm(
      [p(1, '1302'), p(2, '1994'), p(3, '1748'), p(4, '2277'), p(5, '1383')],
      {
        '1': { id: 16, name: 'Cody Hrtyanski', mine: true },
        '2': { id: 16, name: 'Cody Hrtyanski', mine: true },
        '3': { id: 20, name: 'Steven Stocks', mine: false },
        '5': { id: 30, name: 'Carlos Gonzalez', mine: false },
      },
    );
    expect(groups.map((g) => g.key)).toEqual(['mine', 'pm-Carlos Gonzalez', 'pm-Steven Stocks', 'none']);
    expect(groups[0].projects.map((x) => x.code)).toEqual(['1994', '1302']);
    expect(groups[3].projects.map((x) => x.code)).toEqual(['2277']);
  });

  it('has no empty groups', () => {
    expect(groupByPm([p(1, '1302')], {}).map((g) => g.key)).toEqual(['none']);
  });
});
