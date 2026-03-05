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

import { LoadingSkeleton } from '../common/LoadingSkeleton';
import { ErrorBoundary } from '../common/ErrorBoundary';

import ArticleInfoCard from './ArticleInfoCard';
import RevisionTree from './RevisionTree';
import RevisionTable from './RevisionTable';
import RevisionActions from './RevisionActions';
import ArticleWorkflowSection from './ArticleWorkflowSection';
import BOMSection from './BOMSection';

type TabType = 'revisions' | 'bom';

export default function ArticleDetail({ articleId: propArticleId }: { articleId?: number } = {}) {
  const { articleId: routeArticleId } = useParams<{ articleId: string }>();
  const id = propArticleId || (routeArticleId ? parseInt(routeArticleId, 10) : 0);

  const { data, isLoading, error } = useArticle(id);
  const [selectedRevisionId, setSelectedRevisionId] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>('revisions');

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
      <div className="flex bg-slate-900">
        {/* Sidebar: Revision Tree */}
        <div className="w-64 border-r border-slate-700 overflow-y-auto max-h-screen">
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

            {/* Tab Bar */}
            <div className="flex gap-1 mt-6 mb-4 border-b border-slate-700">
              {(['revisions', 'bom'] as TabType[]).map(tab => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`px-4 py-2 text-sm font-medium capitalize transition border-b-2 -mb-px ${
                    activeTab === tab
                      ? 'border-blue-500 text-blue-400'
                      : 'border-transparent text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {tab === 'bom' ? 'BOM' : 'Revisions'}
                </button>
              ))}
            </div>

            {activeTab === 'revisions' && (
              <>
                {/* Actions Bar */}
                <div className="mb-6">
                  <RevisionActions
                    articleId={data.article.id}
                    selectedRevision={selectedRevision}
                    allRevisions={data.revisions}
                  />
                </div>

                {/* Revisions Table */}
                <RevisionTable
                  revisions={data.revisions}
                  selectedRevisionId={selectedRevisionId}
                  onSelectRevision={setSelectedRevisionId}
                  articleId={data.article.id}
                  activeRevisionId={data.article.active_revision_id}
                />

                {/* Workflow Section (Phase 3) */}
                {selectedRevision && (
                  <div className="mt-6">
                    <ArticleWorkflowSection
                      articleId={data.article.id}
                      revisionId={selectedRevision.id}
                    />
                  </div>
                )}
              </>
            )}

            {activeTab === 'bom' && (() => {
              // For BOM: prefer active revision, then selected, then first
              const bomRevision =
                (data.article.active_revision_id && data.revisions.find(r => r.id === data.article.active_revision_id)) ||
                selectedRevision ||
                data.revisions[0];
              return bomRevision ? (
                <BOMSection articleId={data.article.id} revisionId={bomRevision.id} />
              ) : (
                <div className="text-center py-12 text-slate-500 text-sm">
                  Create a revision first (Revisions tab → New Engineering Revision), then add BOM items here.
                </div>
              );
            })()}
          </div>
        </div>
      </div>
    </ErrorBoundary>
  );
}
