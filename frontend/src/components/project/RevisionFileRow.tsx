/**
 * One file of a revision: type chip, name, kind and note, provenance, and the
 * view / open / download / delete actions.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client, { API_BASE_URL } from '../../api/client';
import { UploadedBy } from '../common/UploadedBy';
import { apiErrorMessage } from '../../lib/apiError';
import type { RevisionFile } from './projectTypes';

// File type badge colors
function fileTypeColor(fileType: string): string {
  const colors: Record<string, string> = {
    cad: 'bg-blue-900/50 text-blue-300',
    drawing: 'bg-purple-900/50 text-purple-300',
    picture: 'bg-green-900/50 text-green-300',
    document: 'bg-slate-600 text-slate-200',
    test_result: 'bg-amber-900/50 text-amber-300',
  };
  return colors[fileType] || 'bg-slate-700 text-slate-300';
}

// Revision File List Item
export function RevisionFileRow({
  file,
  isViewing,
  locked,
  onView,
  onOpen,
}: {
  file: RevisionFile;
  isViewing: boolean;
  locked: boolean;
  onView?: () => void;
  onOpen?: () => void;
}) {
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: async () => {
      await client.delete(`/v1/parts/revision-files/${file.id}`);
    },
    onSuccess: () => {
      toast.success('File deleted');
      queryClient.invalidateQueries({ queryKey: ['revision-files', file.revision_id] });
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to delete file'));
    },
  });

  const noPreview = file.cad_format === 'step' && !file.has_viewer;

  return (
    <div className={`flex items-center justify-between p-1.5 rounded border text-xs ${isViewing ? 'bg-blue-900/30 border-blue-600' : 'bg-slate-700 border-slate-600'}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 ${fileTypeColor(file.file_type)}`}>
            {file.file_type.replace(/_/g, ' ')}
          </span>
          <p className="text-slate-100 truncate font-mono text-xs">{file.filename}</p>
          {file.kind && (
            <span data-testid="file-kind" title={file.note ?? undefined}
              className="px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 bg-blue-900/50 text-blue-300">{file.kind}</span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-1">
          <p className="text-slate-400 text-xs">{(file.file_size / 1024 / 1024).toFixed(2)} MB</p>
          {noPreview && <span className="text-yellow-400 text-xs">No 3D preview available</span>}
        </div>
        {file.note && <p data-testid="file-note" className="text-slate-500 text-xs truncate">{file.note}</p>}
        {/* Who put the file on the record and when. */}
        <UploadedBy name={file.uploaded_by_name} at={file.uploaded_at} className="block" />
      </div>
      <div className="ml-1 flex gap-1 flex-shrink-0">
        {file.has_viewer && onView && (
          <button
            onClick={onView}
            disabled={isViewing}
            className="px-2 py-0.5 rounded bg-slate-600 hover:bg-slate-500 disabled:bg-blue-700 text-white font-medium text-xs"
          >
            {isViewing ? 'Viewing' : 'View 3D'}
          </button>
        )}
        {onOpen && (
          <button onClick={onOpen}
            className="px-2 py-0.5 rounded bg-slate-600 hover:bg-slate-500 text-white font-medium text-xs">
            Open
          </button>
        )}
        <a
          href={`${API_BASE_URL}/v1/parts/revision-files/${file.id}/download`}
          download={file.filename}
          className="px-2 py-0.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs"
        >
          Download
        </a>
        {!locked && (
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
            className="px-2 py-0.5 rounded bg-red-600 hover:bg-red-500 disabled:bg-red-700 text-white font-medium text-xs"
          >
            {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
          </button>
        )}
      </div>
    </div>
  );
}
