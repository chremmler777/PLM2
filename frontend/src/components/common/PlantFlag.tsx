/**
 * The plant flag in the project header: Toccoa US, Silao MX, Weissenburg DE.
 * A small inline SVG, because Windows shows emoji flags as plain letters.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

interface PlantRow { id: number; name: string; code: string; location?: string | null }

// plant code -> country; unknown codes fall back to the plant location.
const PLANT_COUNTRY: Record<string, string> = { 'usa-toccoa': 'US', SIL: 'MX', WUG: 'DE', 'main-plant': 'DE' };

export function plantCountry(plant?: PlantRow | null): string | null {
  if (!plant) return null;
  if (PLANT_COUNTRY[plant.code]) return PLANT_COUNTRY[plant.code];
  const loc = (plant.location ?? '').toLowerCase();
  if (/\b(mx|mexico)\b/.test(loc)) return 'MX';
  if (/\b(usa|ga)\b/.test(loc)) return 'US';
  if (/\b(de|germany)\b/.test(loc)) return 'DE';
  return null;
}

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

/** One flag for a plant; nothing when the plant is unknown. */
export function PlantFlag({ plant, testId }: { plant?: PlantRow | null; testId?: string }) {
  const country = plantCountry(plant);
  if (!country || !plant) return null;
  return (
    <span data-testid={testId} title={plant.name} aria-label={plant.name}
      className="inline-flex flex-shrink-0 align-middle rounded-[2px] ring-1 ring-slate-600/80 overflow-hidden">
      <FlagSvg country={country} />
    </span>
  );
}

/** The project's plant flag; plants come from the shared ['plants'] query. */
export function ProjectPlantFlag({ plantId, testId }: { plantId?: number | null; testId?: string }) {
  const { data: plants } = useQuery<PlantRow[]>({
    queryKey: ['plants'],
    queryFn: async () => (await client.get('/v1/plants')).data,
    staleTime: 10 * 60 * 1000,
  });
  return <PlantFlag plant={plants?.find((p) => p.id === plantId)} testId={testId} />;
}
