/**
 * ArticleDetail - Main article detail view
 *
 * Layout: Split view with sidebar (revision tree) and main content
 * - Left: RevisionTree sidebar
 * - Right: ArticleInfoCard, RevisionTable, Actions, Workflow
 */

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useArticle } from '../../hooks/queries/useArticles';
import { RevisionResponse } from '../../types/article';
import { LoadingSkeleton } from '../common/LoadingSkeleton';
import { ErrorBoundary } from '../common/ErrorBoundary';

import ArticleInfoCard from './ArticleInfoCard';
import RevisionTree from './RevisionTree';
import RevisionTable from './RevisionTable';
import RevisionActions from './RevisionActions';
import ArticleWorkflowSection from './ArticleWorkflowSection';

export default function ArticleDetail({ articleId: propArticleId }: { articleId?: number } = {}) {
  const { articleId: routeArticleId } = useParams<{ articleId: string }>();
  const id = propArticleId || (routeArticleId ? parseInt(routeArticleId, 10) : 0);

  const { data, isLoading, error } = useArticle(id);
  const [selectedRevisionId, setSelectedRevisionId] = useState<number | null>(null);

  if (isLoading) {
    return <LoadingSkeleton count={3} />;
  }

  if (error) {
    return (
      <div className="p-6 text-red-600">
        Failed to load article: {error instanceof Error ? error.message : 'Unknown error'}
      </div>
    );
  }

  if (!data) {
    return <div className="p-6 text-slate-400">Article not found</div>;
  }

  const selectedRevision = selectedRevisionId
    ? data.revisions.find(r => r.id === selectedRevisionId)
    : data.article.active_revision_id
    ? data.revisions.find(r => r.id === data.article.active_revision_id)
    : data.revisions[0];

  return (
    <ErrorBoundary>
      <div className="flex h-full bg-slate-900">
        {/* Sidebar: Revision Tree */}
        <div className="w-64 border-r border-slate-700 overflow-y-auto">
          <div className="p-4">
            <h3 className="font-semibold text-slate-100 mb-4">Revisions</h3>
            <RevisionTree
              tree={data.revision_tree}
              selectedRevisionId={selectedRevisionId}
              onSelectRevision={setSelectedRevisionId}
            />
          </div>
        </div>

        {/* Main Content */}
        <div className="flex-1 overflow-y-auto">
          <div className="p-6">
            {/* Article Info */}
            <ArticleInfoCard article={data.article} />

            {/* Actions Bar */}
            <div className="mt-6 mb-6">
              <RevisionActions
                articleId={data.article.id}
                selectedRevision={selectedRevision}
                allRevisions={data.revisions}
              />
            </div>

            {/* Revisions Table */}
            <div className="mt-6">
              <RevisionTable
                revisions={data.revisions}
                selectedRevisionId={selectedRevisionId}
                onSelectRevision={setSelectedRevisionId}
                articleId={data.article.id}
              />
            </div>

            {/* Workflow Section (Phase 3) */}
            {selectedRevision && (
              <div className="mt-6">
                <ArticleWorkflowSection
                  articleId={data.article.id}
                  revisionId={selectedRevision.id}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </ErrorBoundary>
  );
}
