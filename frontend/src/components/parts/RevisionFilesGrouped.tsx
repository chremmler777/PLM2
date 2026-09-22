/** File list of a revision grouped the way engineers look for things:
 *  3D (PCA, DMU, STEP), 2D (drawings), Documents (the rest). */
import { RevisionFileRow, type RevisionFile } from '../../pages/ProjectDetailPage';

// Kept in sync with the backend's INLINE_EXTENSIONS (backend/app/api/v1/items/revision_files.py).
export const INLINE_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp'] as const;

const IMAGE_EXTENSIONS = INLINE_EXTENSIONS.filter((ext) => ext !== '.pdf');

export function docKindFor(file: { mime_type: string; filename: string }): 'pdf' | 'image' | null {
  const lower = file.filename.toLowerCase();
  if (file.mime_type === 'application/pdf' || lower.endsWith('.pdf')) return 'pdf';
  if (IMAGE_EXTENSIONS.some((ext) => lower.endsWith(ext))) return 'image';
  return null;
}

export function canOpenInline(file: { mime_type: string; filename: string }): boolean {
  return docKindFor(file) !== null;
}

const GROUPS: { key: string; label: string; match(f: RevisionFile): boolean }[] = [
  { key: '3d', label: '3D', match: (f) => f.file_type === 'cad' },
  { key: '2d', label: '2D', match: (f) => f.file_type === 'drawing' },
  { key: 'docs', label: 'Documents', match: (f) => f.file_type !== 'cad' && f.file_type !== 'drawing' },
];

interface Props {
  files: RevisionFile[];
  locked: boolean;
  viewingFileId: number | null;
  revisionName: string;
  onView(file: RevisionFile): void;
  onOpen(file: RevisionFile): void;
}

export default function RevisionFilesGrouped({ files, locked, viewingFileId, revisionName, onView, onOpen }: Props) {
  if (files.length === 0) return <p className="text-slate-500 text-xs px-1 py-2">No files on {revisionName} yet</p>;
  return (
    <div className="space-y-2">
      {GROUPS.map((g) => {
        const rows = files.filter(g.match);
        if (rows.length === 0) return null;
        return (
          <div key={g.key}>
            <p className="text-[10px] uppercase tracking-wide text-slate-500 px-1 mb-1">{g.label} ({rows.length})</p>
            <div className="space-y-1">
              {rows.map((file) => (
                <RevisionFileRow key={file.id} file={file} locked={locked} isViewing={viewingFileId === file.id}
                  onView={file.has_viewer ? () => onView(file) : undefined}
                  onOpen={canOpenInline(file) ? () => onOpen(file) : undefined} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
