/**
 * ArticleWorkflowSection - Display workflow progress (placeholder for Phase 3)
 */

interface Props {
  articleId: number;
  revisionId: number;
}

export default function ArticleWorkflowSection({ articleId, revisionId }: Props) {
  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-6">
      <h3 className="font-semibold text-slate-100 mb-4">Workflow</h3>
      <div className="text-center py-8 text-slate-400">
        <p className="mb-2">Workflow management coming in Phase 3</p>
        <p className="text-sm">Track approvals and task assignments</p>
      </div>
    </div>
  );
}
