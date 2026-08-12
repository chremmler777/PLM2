/**
 * AttachmentDropzone — drag-and-drop (or click-to-browse) upload for change
 * attachments. Accepts documents and saved email files (.msg / .eml) dropped
 * from a folder. Files are stored as-is; nothing is parsed.
 *
 * Note: dragging an email straight out of the Outlook desktop app does not
 * yield a file in the browser — save it as .msg first, then drop that.
 */
import { useRef, useState } from 'react';
import { toast } from 'sonner';
import { changesApi } from '../../api/changes';
import { apiErrorMessage } from '../../lib/apiError';
import { t } from '../../i18n/cmLabels';
import type { AttachmentKind } from '../../types/change';

const MAX_BYTES = 50 * 1024 * 1024;
// Hint for the browse dialog; drops themselves are not restricted by extension.
const ACCEPT = '.pdf,.ppt,.pptx,.doc,.docx,.xls,.xlsx,.msg,.eml,.png,.jpg,.jpeg,.txt';

interface Props {
  changeId: number;
  onUploaded: () => void;
  /** Where these uploads sit in the needs-info loop. Plain document slots pass
   *  nothing and the file stays 'general'. */
  kind?: AttachmentKind;
  respondsToId?: number;
  concernId?: number;
  assessmentId?: number;
  /** A vendor quote files itself under the offer it prices. */
  costingOfferId?: number;
  /** Slot label — the needs-info and response slots say what they are for. */
  label?: string;
  /** Inside a card the zone is one quiet line, not a big dashed billboard. */
  compact?: boolean;
}

export default function AttachmentDropzone({
  changeId, onUploaded, kind, respondsToId, concernId, assessmentId,
  costingOfferId, label, compact = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);

  const upload = async (files: File[]) => {
    if (files.length === 0) return;
    const tooBig = files.filter((f) => f.size > MAX_BYTES);
    const ok = files.filter((f) => f.size <= MAX_BYTES);
    tooBig.forEach((f) =>
      toast.error(t('attach.tooLarge').replace('{name}', f.name)),
    );
    if (ok.length === 0) return;

    setBusy(true);
    let uploaded = 0;
    for (const f of ok) {
      try {
        await changesApi.uploadAttachment(changeId, f,
          { kind, respondsToId, concernId, assessmentId, costingOfferId });
        uploaded += 1;
      } catch (e) {
        toast.error(apiErrorMessage(e, t('attach.failed').replace('{name}', f.name)));
      }
    }
    setBusy(false);
    if (uploaded > 0) {
      toast.success(t('attach.uploaded').replace('{n}', String(uploaded)));
      onUploaded();
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length === 0) {
      // Outlook-direct drags and text drags arrive with no File — guide the user.
      toast.error(t('attach.noFile'));
      return;
    }
    void upload(files);
  };

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-label={label ?? t('attach.dropHere')}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={
          'flex items-center justify-center gap-2 rounded-lg border border-dashed ' +
          'text-center cursor-pointer transition-colors ' +
          (compact ? 'px-3 py-2 text-xs ' : 'flex-col border-2 px-4 py-6 ') +
          (dragging
            ? 'border-sky-500 bg-sky-500/10 text-sky-200'
            : 'border-slate-600 bg-slate-900/40 text-slate-400 hover:border-slate-500')
        }
      >
        <span className={compact ? 'leading-none' : 'text-2xl leading-none'} aria-hidden>
          {busy ? '⏳' : '📎'}
        </span>
        <span className={compact ? 'text-xs' : 'text-sm'}>
          {busy ? t('attach.uploading') : label ?? t('attach.dropHere')}
        </span>
        {!compact && <span className="text-xs text-slate-500">{t('attach.hint')}</span>}
      </div>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          void upload(files);
          e.target.value = '';
        }}
      />
    </div>
  );
}
