/** The labelled KTX / Tier 1 / OEM numbers of a part on one line; missing ones are left out. */
import { Fragment } from 'react';
import { labelledNumbers } from '../../lib/partDisplay';

export default function PartNumbers({ part, testIdPrefix, className = '' }: {
  part: { part_number: string; tier1_part_number?: string | null; customer_part_number?: string | null };
  testIdPrefix: string;
  className?: string;
}) {
  const numbers = labelledNumbers(part);
  return (
    <span data-testid={testIdPrefix} className={`block min-w-0 truncate ${className}`}>
      {numbers.map((n, i) => (
        <Fragment key={n.key}>
          {i > 0 && <span className="text-slate-600"> · </span>}
          <span data-testid={`${testIdPrefix}-${n.key}`} title={n.title} className="whitespace-nowrap">
            <span className="text-slate-500">{n.label} </span>
            <span className="font-mono text-slate-300">{n.value}</span>
          </span>
        </Fragment>
      ))}
    </span>
  );
}
