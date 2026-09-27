/**
 * Project team (spec §18): the mark on a task the viewer sees as backup. The
 * project has a responsible for this role; the row is listed so the backup
 * can step in, but it is the main's work and does not count for the viewer.
 */
import { t } from '../../i18n/cmLabels'

export default function BackupChip({ mainName, className = '' }: { mainName?: string | null; className?: string }) {
  return (
    <span data-testid="backup-chip" title={t('team.backupHint')}
      className={`inline-flex flex-wrap items-center gap-x-1.5 align-middle ${className}`}>
      <span className="rounded border border-slate-600 px-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        {t('team.backup')}
      </span>
      {mainName && (
        <span className="text-xs text-slate-400">{t('team.main').replace('{x}', mainName)}</span>
      )}
    </span>
  )
}
