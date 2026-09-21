/**
 * ColourSwatch - small rounded square showing a paint's colour.
 * Falls back to a grey hatch pattern when no hex is set.
 */

interface ColourSwatchProps {
  hex?: string | null;
  code?: string | null;
}

const HATCH_BACKGROUND =
  'repeating-linear-gradient(45deg, #64748b 0, #64748b 2px, #334155 2px, #334155 6px)';

export default function ColourSwatch({ hex, code }: ColourSwatchProps) {
  const style = hex
    ? { backgroundColor: hex }
    : { backgroundImage: HATCH_BACKGROUND };

  return (
    <span
      role="img"
      aria-label={code || hex || 'no colour'}
      title={code || undefined}
      className="inline-block w-4 h-4 rounded border border-slate-600 flex-shrink-0"
      style={style}
    />
  );
}
