/**
 * ArticleWorkflowSection - Display workflow progress (placeholder for Phase 3)
 */

interface Props {
  articleId: number;
  revisionId: number;
}

export default function ArticleWorkflowSection({ articleId, revisionId }: Props) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 p-6">
      <h3 className="font-semibold text-gray-900 mb-4">Workflow</h3>
      <div className="text-center py-8 text-gray-500">
        <p className="mb-2">Workflow management coming in Phase 3</p>
        <p className="text-sm">Track approvals and task assignments</p>
      </div>
    </div>
  );
}
