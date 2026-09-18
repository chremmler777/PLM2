/** One way to print a revision: name plus the customer's own index, "E2 · B". */
export function revisionLabel(name: string | null | undefined, index?: string | null): string {
  if (!name) return '';
  const idx = (index ?? '').trim();
  return idx ? `${name} · ${idx}` : name;
}

export default function RevisionBadge({ name, index, phase, testId }: {
  name: string | null | undefined; index?: string | null; phase?: 'review' | 'official' | null; testId?: string;
}) {
  if (!name) return <span data-testid={testId} className="text-xs text-slate-500">no data</span>;
  return (
    <span data-testid={testId} title={phase ?? undefined}
      className={`text-xs px-1.5 rounded font-mono ${phase === 'official' ? 'bg-amber-900/40 text-amber-300' : 'bg-blue-900/40 text-blue-300'}`}>
      {revisionLabel(name, index)}
    </span>
  );
}
