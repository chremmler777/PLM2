/**
 * Plant country flags: which plant a project or part belongs to (Toccoa US,
 * Silao MX, Weissenburg DE) and both when a part is shared across plants.
 * Small inline SVGs, because Windows shows emoji flags as plain letters.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

const PLANT_NAME: Record<string, string> = {
  US: 'Toccoa (USA)',
  MX: 'Silao (Mexico)',
  DE: 'Weissenburg (Germany)',
};

function FlagSvg({ country }: { country: string }) {
  const common = { width: 16, height: 11, viewBox: '0 0 16 11', 'aria-hidden': true as const };
  if (country === 'MX') {
    return (
      <svg {...common}>
        <rect width="16" height="11" fill="#fff" />
        <rect width="5.33" height="11" fill="#006847" />
        <rect x="10.67" width="5.33" height="11" fill="#ce1126" />
        <circle cx="8" cy="5.5" r="1.4" fill="#8c6a2e" />
      </svg>
    );
  }
  if (country === 'US') {
    return (
      <svg {...common}>
        <rect width="16" height="11" fill="#fff" />
        {[0, 2, 4, 6, 8, 10, 12].map((i) => <rect key={i} y={(i * 11) / 13} width="16" height={11 / 13} fill="#b22234" />)}
        <rect width="7" height="5.9" fill="#3c3b6e" />
      </svg>
    );
  }
  if (country === 'DE') {
    return (
      <svg {...common}>
        <rect width="16" height="3.67" fill="#000" />
        <rect y="3.67" width="16" height="3.67" fill="#dd0000" />
        <rect y="7.33" width="16" height="3.67" fill="#ffce00" />
      </svg>
    );
  }
  return null;
}

export function PlantFlags({ countries, testId }: { countries?: string[] | null; testId?: string }) {
  const known = (countries ?? []).filter((c) => PLANT_NAME[c]);
  if (known.length === 0) return null;
  const title = known.length > 1
    ? `Both plants: ${known.map((c) => PLANT_NAME[c]).join(' + ')}`
    : PLANT_NAME[known[0]];
  return (
    <span data-testid={testId} title={title} aria-label={title}
      className="inline-flex flex-shrink-0 items-center gap-0.5 align-middle">
      {known.map((c) => (
        <span key={c} className="inline-flex rounded-[2px] ring-1 ring-slate-600/80 overflow-hidden">
          <FlagSvg country={c} />
        </span>
      ))}
    </span>
  );
}

/** Countries of every part of a project, {part_id: ["US", "MX"]}. One request
 *  per project; every row and header on the page shares it. */
export function useProjectPartCountries(projectId?: number | null) {
  return useQuery<Record<string, string[]>>({
    queryKey: ['project-part-countries', projectId],
    queryFn: async () => (await client.get(`/v1/plants/projects/${projectId}/part-countries`)).data,
    enabled: !!projectId,
    staleTime: 5 * 60 * 1000,
  });
}

export function PartPlantFlags({ projectId, partId, testId }:
  { projectId?: number | null; partId: number; testId?: string }) {
  const { data } = useProjectPartCountries(projectId);
  return <PlantFlags countries={data?.[String(partId)]} testId={testId} />;
}
