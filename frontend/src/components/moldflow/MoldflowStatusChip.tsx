/** A Moldflow status as a small chip, toned by what it asks of the reader (amber: needs something). */
import { MF_STATUS_LABELS, MF_STATUS_TONE, type MfStatus, type MfTone } from '../../api/moldflow';

export const MF_TONE_CLASS: Record<MfTone, string> = {
  slate: 'bg-slate-700 text-slate-300',
  amber: 'bg-amber-600/25 text-amber-200',
  sky: 'bg-sky-900/60 text-sky-200',
  emerald: 'bg-emerald-900/50 text-emerald-200',
};

export default function MoldflowStatusChip({ status }: { status: MfStatus }) {
  const tone = MF_STATUS_TONE[status] ?? 'slate';
  return (
    <span data-testid="mf-status-chip" className={`px-1.5 rounded text-[11px] leading-5 whitespace-nowrap ${MF_TONE_CLASS[tone]}`}>
      {MF_STATUS_LABELS[status] ?? status}
    </span>
  );
}
