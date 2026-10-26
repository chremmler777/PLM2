/**
 * The project team in its own dialog (Christoph 2026-10-26): opened from the
 * header's Team button and the ⋯ menu, instead of the card squeezed into the
 * w-80 menu. Same rules as the card (ProjectTeamCard detailed): the
 * responsible and backup per department, changeable by PM members and
 * admins, plus every member with name, email and a badge.
 */
import Dialog from '../common/Dialog';
import { ProjectTeamCard } from './ProjectTeamCard';
import { t } from '../../i18n/cmLabels';

export default function ProjectTeamDialog({ projectId, open, onClose }: {
  projectId: number; open: boolean; onClose(): void;
}) {
  return (
    <Dialog open={open} onClose={onClose} size="xl" data-testid="project-team-dialog"
      title={t('team.title')} description={t('team.dialogHint')}>
      <ProjectTeamCard projectId={projectId} detailed />
    </Dialog>
  );
}
