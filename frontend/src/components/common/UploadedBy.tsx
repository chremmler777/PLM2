/**
 * Provenance line for a file row: who put it on the record, and when.
 * Falls back to the date alone when the uploader is unknown (older rows).
 * Shared so every file list in the app reads the same way.
 */
export function UploadedBy({ name, at, className = '' }: {
  name?: string | null
  at?: string | null
  className?: string
}) {
  if (!at && !name) return null
  return (
    <span data-testid="uploaded-by" className={`text-xs text-slate-500 ${className}`}>
      {name ? `${name}${at ? ' · ' : ''}` : ''}
      {at ? new Date(at).toLocaleDateString() : ''}
    </span>
  )
}
