/**
 * LoadingSkeleton - Animated loading placeholder
 */

interface Props {
  count?: number;
}

export function LoadingSkeleton({ count = 1 }: Props) {
  return (
    <div className="space-y-4 p-6">
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-slate-700 rounded-lg h-16 animate-pulse" />
      ))}
    </div>
  );
}
