/**
 * SepItemFiles — every SEP work item is a file slot. The row carries a 📎 count
 * badge, a quiet drop strip, and (expanded) the list of what is parked there:
 * filename as a download link, size, who put it there, and a remove that asks
 * once, inline. The forms engine stays; it just no longer leads the row.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  deleteItemFile, formatBytes, itemFileDownloadUrl, listItemFiles, uploadItemFiles,
} from '../../api/sepFiles';
import { apiErrorMessage } from '../../lib/apiError';
import { UploadedBy } from '../common/UploadedBy';
import type { SepItemFile } from '../../types/sep';

export default function SepItemFiles({ itemId, projectId, fileCount = 0, locked = false }: {
  itemId: number;
  projectId: number;
  /** Count from the SEP payload — the badge without fetching every item's list. */
  fileCount?: number;
  locked?: boolean;
}) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [confirming, setConfirming] = useState<number | null>(null);

  const { data: files } = useQuery({
    queryKey: ['sep-item-files', itemId],
    queryFn: () => listItemFiles(itemId),
    enabled: expanded,
  });

  // The count the row shows: the live list once we have it, the payload's
  // number until then, so the badge never disagrees with what is listed.
  const count = files?.length ?? fileCount;

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['sep-item-files', itemId] });
    queryClient.invalidateQueries({ queryKey: ['sep', projectId] });
    queryClient.invalidateQueries({ queryKey: ['sep-files', projectId] });
  };

  const upload = useMutation({
    mutationFn: (picked: File[]) => uploadItemFiles(itemId, picked),
    onSuccess: (created) => {
      setExpanded(true);
      refresh();
      toast.success(`${created.length} file${created.length === 1 ? '' : 's'} attached`);
    },
    // A 413 comes back as `File <name> exceeds 100MB` — say exactly that.
    onError: (e: unknown) => toast.error(apiErrorMessage(e, 'Upload failed')),
  });

  const remove = useMutation({
    mutationFn: (fileId: number) => deleteItemFile(itemId, fileId),
    onSuccess: () => {
      setConfirming(null);
      refresh();
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, 'Could not remove the file')),
  });

  const take = (picked: File[]) => {
    if (picked.length === 0 || locked || upload.isPending) return;
    upload.mutate(picked);
  };

  const busy = upload.isPending;

  return (
    <div className="mt-1">
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          data-testid={`sep-files-badge-${itemId}`}
          aria-expanded={expanded}
          className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${
            count > 0
              ? 'border-sky-500/30 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20'
              : 'border-slate-600 text-slate-400 hover:border-slate-500'
          }`}
        >
          📎 {count}
        </button>

        {!locked && (
          <label
            data-testid={`sep-files-drop-${itemId}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const dropped = Array.from(e.dataTransfer?.files ?? []);
              if (dropped.length === 0) {
                toast.error('That drop carried no file — save it to disk first, then drop it.');
                return;
              }
              take(dropped);
            }}
            className={`flex-1 min-w-0 cursor-pointer rounded border border-dashed px-2 py-1 text-[11px] transition-colors ${
              busy
                ? 'border-slate-700 bg-slate-900/40 text-slate-500 cursor-wait'
                : dragging
                  ? 'border-sky-500 bg-sky-500/10 text-sky-200'
                  : 'border-slate-600 bg-slate-900/40 text-slate-400 hover:border-slate-500'
            }`}
          >
            {busy ? 'Uploading…' : 'Drop files or click'}
            <input
              type="file"
              multiple
              disabled={busy}
              data-testid={`sep-files-input-${itemId}`}
              className="hidden"
              onChange={(e) => {
                take(Array.from(e.target.files ?? []));
                e.target.value = '';
              }}
            />
          </label>
        )}
      </div>

      {expanded && (
        <ul className="mt-1 ml-1 divide-y divide-slate-700/40" data-testid={`sep-files-list-${itemId}`}>
          {(files ?? []).map((f: SepItemFile) => (
            <li key={f.id} className="flex items-center gap-2 py-1 text-xs group">
              {!locked && (
                confirming === f.id ? (
                  <span className="flex items-center gap-1 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => remove.mutate(f.id)}
                      disabled={remove.isPending}
                      className="rounded bg-red-600/80 px-1.5 py-0.5 text-[10px] text-white hover:bg-red-500 disabled:opacity-50"
                    >
                      Remove
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirming(null)}
                      className="text-[10px] text-slate-400 hover:text-slate-200"
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    aria-label={`Delete ${f.filename}`}
                    title="Remove file"
                    onClick={() => setConfirming(f.id)}
                    className="flex-shrink-0 text-slate-600 hover:text-red-400 opacity-40 group-hover:opacity-100 focus:opacity-100 transition-opacity"
                  >
                    ✕
                  </button>
                )
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate">
                  <a
                    href={itemFileDownloadUrl(itemId, f.id)}
                    download={f.filename}
                    className="text-sky-300 hover:text-sky-200 hover:underline"
                  >
                    {f.filename}
                  </a>
                  <span className="ml-1.5 text-slate-500">{formatBytes(f.size_bytes)}</span>
                </span>
                <UploadedBy name={f.uploaded_by_name} at={f.uploaded_at} className="block" />
              </span>
            </li>
          ))}
          {(files ?? []).length === 0 && (
            <li className="py-1 text-xs text-slate-500">No files on this topic yet.</li>
          )}
        </ul>
      )}
    </div>
  );
}
