/**
 * Articles Page - Main article listing and detail view
 */

import { useState } from 'react';
import { useArticles, useCreateArticle } from '../hooks/queries/useArticles';
import { ArticleTypeEnum, SourcingTypeEnum } from '../types/article';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { toast } from 'sonner';
import ArticleDetail from '../components/articles/ArticleDetail';

export default function ArticlesPage() {
  const { data: articles, isLoading } = useArticles();
  const [selectedArticleId, setSelectedArticleId] = useState<number | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const createArticle = useCreateArticle();

  const [formData, setFormData] = useState({
    article_number: '',
    name: '',
    description: '',
    article_type: ArticleTypeEnum.INJECTION_TOOL,
    sourcing_type: SourcingTypeEnum.INTERNAL,
  });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const newArticle = await createArticle.mutateAsync(formData);
      toast.success('Article created');
      setSelectedArticleId(newArticle.id);
      setShowCreateModal(false);
      setFormData({
        article_number: '',
        name: '',
        description: '',
        article_type: ArticleTypeEnum.INJECTION_TOOL,
        sourcing_type: SourcingTypeEnum.INTERNAL,
      });
    } catch (error) {
      toast.error('Failed to create article');
    }
  };

  if (selectedArticleId) {
    return (
      <div>
        <button
          onClick={() => setSelectedArticleId(null)}
          className="m-4 px-3 py-1 bg-gray-200 text-gray-900 rounded hover:bg-gray-300 text-sm"
        >
          ← Back to List
        </button>
        <ArticleDetail />
      </div>
    );
  }

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold text-gray-900">Articles</h1>
        <button
          onClick={() => setShowCreateModal(true)}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 font-medium"
        >
          New Article
        </button>
      </div>

      {isLoading ? (
        <LoadingSkeleton count={5} />
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          {articles && articles.length > 0 ? (
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-gray-700 uppercase">
                    Number
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-gray-700 uppercase">
                    Name
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-gray-700 uppercase">
                    Type
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-semibold text-gray-700 uppercase">
                    Sourcing
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {articles.map((article) => (
                  <tr
                    key={article.id}
                    onClick={() => setSelectedArticleId(article.id)}
                    className="hover:bg-gray-50 cursor-pointer"
                  >
                    <td className="px-6 py-4 font-mono font-semibold text-gray-900">
                      {article.article_number}
                    </td>
                    <td className="px-6 py-4 text-gray-900">{article.name}</td>
                    <td className="px-6 py-4 text-gray-600 capitalize">
                      {article.article_type.replace(/_/g, ' ')}
                    </td>
                    <td className="px-6 py-4 text-gray-600 capitalize">
                      {article.sourcing_type}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="px-6 py-12 text-center text-gray-500">
              <p className="mb-3">No articles yet</p>
              <button
                onClick={() => setShowCreateModal(true)}
                className="text-blue-600 hover:text-blue-700 font-medium"
              >
                Create the first one
              </button>
            </div>
          )}
        </div>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-lg max-w-md w-full mx-4">
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">Create Article</h2>
              <form onSubmit={handleCreate} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Article Number
                  </label>
                  <input
                    type="text"
                    required
                    value={formData.article_number}
                    onChange={(e) =>
                      setFormData({ ...formData, article_number: e.target.value })
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., PART-001"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Name
                  </label>
                  <input
                    type="text"
                    required
                    value={formData.name}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Type
                  </label>
                  <select
                    value={formData.article_type}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        article_type: e.target.value as ArticleTypeEnum,
                      })
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500"
                  >
                    <option value={ArticleTypeEnum.INJECTION_TOOL}>Injection Tool</option>
                    <option value={ArticleTypeEnum.ASSEMBLY_EQUIPMENT}>Assembly Equipment</option>
                    <option value={ArticleTypeEnum.PURCHASED_PART}>Purchased Part</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Sourcing
                  </label>
                  <select
                    value={formData.sourcing_type}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        sourcing_type: e.target.value as SourcingTypeEnum,
                      })
                    }
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500"
                  >
                    <option value={SourcingTypeEnum.INTERNAL}>Internal</option>
                    <option value={SourcingTypeEnum.EXTERNAL}>External</option>
                  </select>
                </div>

                <div className="flex gap-3 justify-end pt-4">
                  <button
                    type="button"
                    onClick={() => setShowCreateModal(false)}
                    className="px-4 py-2 bg-gray-200 text-gray-900 rounded-md hover:bg-gray-300 font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={createArticle.isPending}
                    className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-blue-400 font-medium"
                  >
                    {createArticle.isPending ? 'Creating...' : 'Create'}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
