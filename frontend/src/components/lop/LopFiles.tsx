/**
 * Files on a LOP line. FileDrop is the quiet strip that takes a drop or a
 * click; LopFiles lists what is attached to an existing line (name as a
 * download link, size, who, when) with a remove that asks once, inline.
 * The project team and the PM attach; the PM removes any file, everybody
 * else only their own.
 */
import { useState } from 'react'
import { Paperclip } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { lopApi, lopFileUrl, lopKeys } from '../../api/lop'
import { formatBytes } from '../../api/sepFiles'
import { shortDay } from '../../lib/lop'
import type { LopFile, LopLine } from '../../types/lop'
import { InlineError } from './lopUi'
import { useLopWrite } from './useLopWrite'

export const NO_FILE_IN_DROP = 'That drop carried no file. Save it to disk first (a mail as .msg), then drop it.'

export function FileDrop({ onFiles, busy = false, testId, label = 'Drop files here or click to attach' }: {
  onFiles(files: File[]): void; busy?: boolean; testId?: string; label?: string
}) {
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <div>
      <label data-testid={testId}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const dropped = Array.from(e.dataTransfer?.files ?? [])
          setError(dropped.length === 0 ? NO_FILE_IN_DROP : null)
          if (dropped.length > 0 && !busy) onFiles(dropped)
        }}
        className={`flex cursor-pointer items-center gap-1.5 rounded border border-dashed px-2 py-1.5 text-[11px] transition-colors ${
          busy ? 'cursor-wait border-slate-700 bg-slate-900/40 text-slate-500'
            : dragging ? 'border-sky-500 bg-sky-500/10 text-sky-200'
              : 'border-slate-600 bg-slate-900/40 text-slate-400 hover:border-slate-500'}`}>
        <Paperclip size={12} aria-hidden="true" />
        {busy ? 'Uploading…' : label}
        <input type="file" multiple disabled={busy} className="hidden"
          data-testid={testId ? `${testId}-input` : undefined}
          onChange={(e) => {
            const picked = Array.from(e.target.files ?? [])
            setError(null)
            if (picked.length > 0) onFiles(picked)
            e.target.value = ''
          }} />
      </label>
      <InlineError>{error}</InlineError>
    </div>
  )
}

export default function LopFiles({ line, projectId, canAttach }: {
  line: LopLine; projectId: number; canAttach: boolean
}) {
  const id = line.id!
  const [confirming, setConfirming] = useState<number | null>(null)
  const files = useQuery({ queryKey: lopKeys.files(projectId, id), queryFn: () => lopApi.files(id) })
  const attach = useLopWrite(projectId, (picked: File[]) => lopApi.attachFiles(id, picked),
    { fallback: 'The files could not be attached.', refreshPdb: false })
  const remove = useLopWrite(projectId, (fileId: number) => lopApi.removeFile(id, fileId),
    { fallback: 'The file could not be removed.', onDone: () => setConfirming(null), refreshPdb: false })
  const list: LopFile[] = Array.isArray(files.data) ? files.data : []
  if (!canAttach && list.length === 0 && !files.isError) return null
  return (
    <div data-testid={`lop-files-${id}`} className="flex flex-col gap-1">
      <span className="text-[11px] text-slate-400">Files</span>
      {list.length > 0 && (
        <ul className="divide-y divide-slate-700/40" aria-label="Attached files">
          {list.map((f) => (
            <li key={f.id} className="flex items-center gap-2 py-1 text-xs">
              <a href={lopFileUrl(id, f.id)} download={f.filename}
                className="min-w-0 truncate text-sky-300 hover:text-sky-200 hover:underline">{f.filename}</a>
              <span className="whitespace-nowrap text-[11px] text-slate-500">
                {formatBytes(f.size_bytes)} · {f.uploaded_by_name ?? 'unknown'}{f.uploaded_at ? ` · ${shortDay(f.uploaded_at)}` : ''}
              </span>
              {f.can_delete && (confirming === f.id ? (
                <span className="ml-auto flex items-center gap-1">
                  <button type="button" disabled={remove.pending} onClick={() => remove.run(f.id)}
                    className="rounded bg-red-600/80 px-1.5 py-0.5 text-[10px] text-white hover:bg-red-500 disabled:opacity-50">Remove</button>
                  <button type="button" onClick={() => setConfirming(null)}
                    className="text-[10px] text-slate-400 hover:text-slate-200">Keep</button>
                </span>
              ) : (
                <button type="button" aria-label={`Remove ${f.filename}`} onClick={() => setConfirming(f.id)}
                  className="ml-auto text-[11px] text-slate-500 hover:text-red-300">Remove</button>
              ))}
            </li>
          ))}
        </ul>
      )}
      {canAttach && <FileDrop testId={`lop-files-drop-${id}`} busy={attach.pending} onFiles={(picked) => attach.run(picked)} />}
      {files.isError && <InlineError>The files could not be loaded.</InlineError>}
      <InlineError>{attach.error ?? remove.error}</InlineError>
    </div>
  )
}
