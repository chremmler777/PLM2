/**
 * SepDocumentsTab — everything dropped on the project's SEP work items, in one
 * place: gate, then topic, then the files under it. Read-only on purpose;
 * adding and removing happens on the row that owns the file.
 */
import { useQuery } from '@tanstack/react-query';
import { formatBytes, itemFileDownloadUrl, projectSepFiles } from '../../api/sepFiles';
import { UploadedBy } from '../common/UploadedBy';
import type { SepProjectFilesGate } from '../../types/sep';

export default function SepDocumentsTab({ projectId }: { projectId: number }) {
  const { data: gates, isLoading } = useQuery({
    queryKey: ['sep-files', projectId],
    queryFn: () => projectSepFiles(projectId),
  });

  if (isLoading) return <div className="text-xs text-slate-500">Loading documents…</div>;

  const withFiles = (gates ?? []).filter((g: SepProjectFilesGate) => g.items.length > 0);

  if (withFiles.length === 0) {
    return (
      <div className="py-6 text-center text-xs text-slate-500" data-testid="sep-documents-empty">
        No documents yet. Drop files on a topic to collect them.
      </div>
    );
  }

  return (
    <div className="space-y-3 max-h-[28rem] overflow-y-auto pr-1" data-testid="sep-documents">
      {withFiles.map((g) => (
        <div key={g.gate_id} data-testid={`sep-doc-gate-${g.gate_id}`}>
          <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">
            {g.gate_code} — {g.phase_en} (
            {g.items.reduce((n, i) => n + i.files.length, 0)})
          </div>
          <div className="space-y-2">
            {g.items.map((item) => (
              <div key={item.item_id} data-testid={`sep-doc-item-${item.item_id}`}
                   className="rounded bg-slate-900/40 px-2 py-1.5">
                <div className="text-xs text-slate-300">
                  <span className="text-slate-500 mr-1.5">{item.item_no}</span>
                  {item.title_en}
                  <span className="ml-1.5 text-slate-500">· {item.department}</span>
                </div>
                <ul className="mt-1 divide-y divide-slate-700/40">
                  {item.files.map((f) => (
                    <li key={f.id} className="py-1 text-xs">
                      <span className="block truncate">
                        📎{' '}
                        <a
                          href={itemFileDownloadUrl(item.item_id, f.id)}
                          download={f.filename}
                          className="text-sky-300 hover:text-sky-200 hover:underline"
                        >
                          {f.filename}
                        </a>
                        <span className="ml-1.5 text-slate-500">{formatBytes(f.size_bytes)}</span>
                      </span>
                      <UploadedBy name={f.uploaded_by_name} at={f.uploaded_at} className="block" />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
