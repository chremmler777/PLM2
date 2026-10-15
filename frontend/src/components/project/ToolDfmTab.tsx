/**
 * DFM tab for a tool (or, with a project scope, the general tooling DFM in
 * the project status panel): the DFM archive. PDFs opened from the ledger
 * open in their own window (the archive's default), not in a pane here.
 */
import DfmArchive from '../dfm/DfmArchive';
import { toolScope, type DfmScope } from '../../api/dfm';

type Props =
  | { partId: number; scope?: never; projectId?: number | null }
  | { scope: DfmScope; partId?: never; projectId?: number | null };

export default function ToolDfmTab({ partId, scope, projectId = null }: Props) {
  return <DfmArchive scope={scope ?? toolScope(partId!)} projectId={projectId} />;
}
