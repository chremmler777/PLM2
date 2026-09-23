/** The labelled KTX / Tier 1 / OEM numbers of a part; missing ones are left out. Numbers wrap as whole units
 * instead of being cut off, so the OEM number stays readable in a narrow list. */
import { Fragment } from 'react';
import { labelledNumbers } from '../../lib/partDisplay';

export default function PartNumbers({ part, testIdPrefix, className = '' }: {
  part: { part_number: string; tier1_part_number?: string | null; customer_part_number?: string | null };
  testIdPrefix: string;
  className?: string;
}) {
  const numbers = labelledNumbers(part);
  return (
    <span data-testid={testIdPrefix} className={`flex flex-wrap items-baseline min-w-0 ${className}`}>
      {numbers.map((n, i) => (
        <Fragment key={n.key}>
          {i > 0 && <span className="text-slate-600 whitespace-pre" aria-hidden="true">{' · '}</span>}
          <span data-testid={`${testIdPrefix}-${n.key}`} title={n.title} className="whitespace-nowrap">
            <span className="text-slate-500">{n.label} </span>
            <span className="font-mono text-slate-300">{n.value}</span>
          </span>
        </Fragment>
      ))}
    </span>
  );
}
