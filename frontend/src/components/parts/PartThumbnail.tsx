/**
 * Square part picture on a neutral slate tile. With no thumbnail (or one
 * that fails to load) a placeholder icon keeps the tile, so rows stay aligned.
 */
import { useState } from 'react';
import { thumbnailSrc } from '../../lib/thumbnail';

const SIZES = { sm: 'w-10 h-10', lg: 'w-24 h-24' } as const;

export default function PartThumbnail({ url, name, size = 'sm', testId }: {
  url: string | null | undefined;
  name: string;
  size?: keyof typeof SIZES;
  testId?: string;
}) {
  const src = thumbnailSrc(url);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showImage = !!src && failedSrc !== src;
  return (
    <span
      data-testid={testId}
      className={`${SIZES[size]} flex-shrink-0 inline-flex items-center justify-center overflow-hidden rounded border border-slate-700 bg-slate-700/40`}
    >
      {showImage ? (
        <img src={src} alt={name} loading="lazy" className="w-full h-full object-contain" onError={() => setFailedSrc(src)} />
      ) : (
        <svg data-testid={testId ? `${testId}-placeholder` : undefined} role="img" aria-label={`${name}: no picture`}
          viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5}
          className={`${size === 'lg' ? 'w-10 h-10' : 'w-5 h-5'} text-slate-500`}>
          <path d="M12 3 20 7.5v9L12 21l-8-4.5v-9L12 3Z" strokeLinejoin="round" />
          <path d="M4 7.5 12 12l8-4.5M12 12v9" strokeLinejoin="round" />
        </svg>
      )}
    </span>
  );
}
