/** A revision as "E1 · 001": our E level bold, the customer's index in normal weight. */
export default function RevisionLabel({ name, index, testId }: {
  name: string | null | undefined;
  index?: string | null;
  testId?: string;
}) {
  if (!name) return null;
  const idx = (index ?? '').trim();
  return (
    <span data-testid={testId}>
      <span className="font-bold">{name}</span>
      {idx && <span className="font-normal"> · {idx}</span>}
    </span>
  );
}
