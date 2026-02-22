/**
 * ArticleInfoCard - Display and edit article metadata
 */

import { useState } from 'react';
import { ArticleResponse } from '../../types/article';
import { useUpdateArticle } from '../../hooks/queries/useArticles';
import { toast } from 'sonner';

interface Props {
  article: ArticleResponse;
}

export default function ArticleInfoCard({ article }: Props) {
  const [isEditing, setIsEditing] = useState(false);
  const [name, setName] = useState(article.name);
  const [description, setDescription] = useState(article.description || '');
  const [sourcing, setSourcing] = useState(article.sourcing_type);

  const updateArticle = useUpdateArticle(article.id);

  const handleSave = async () => {
    try {
      await updateArticle.mutateAsync({
        name: name !== article.name ? name : undefined,
        description: description !== (article.description || '') ? description : undefined,
        sourcing_type: sourcing !== article.sourcing_type ? sourcing : undefined,
      });
      toast.success('Article updated');
      setIsEditing(false);
    } catch (error) {
      toast.error('Failed to update article');
    }
  };

  return (
    <div className="bg-slate-800 rounded-lg p-6 border border-slate-700">
      <div className="flex justify-between items-start">
        <div className="flex-1">
          <div className="flex items-center gap-3 mb-4">
            <div>
              <p className="text-sm text-slate-400">Article Number</p>
              <p className="text-lg font-mono font-semibold text-slate-100">
                {article.article_number}
              </p>
            </div>
            <div>
              <p className="text-sm text-slate-400">Type</p>
              <p className="text-sm font-medium text-slate-100">
                {article.article_type.replace(/_/g, ' ')}
              </p>
            </div>
            <div>
              <p className="text-sm text-slate-400">Classification</p>
              <span className={`inline-block px-2 py-1 rounded text-xs font-semibold ${
                article.data_classification === 'strictly_confidential'
                  ? 'bg-red-100 text-red-800'
                  : article.data_classification === 'confidential'
                  ? 'bg-orange-100 text-orange-800'
                  : 'bg-blue-100 text-blue-800'
              }`}>
                {article.data_classification.replace(/_/g, ' ')}
              </span>
            </div>
          </div>

          {isEditing ? (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-200 mb-1">
                  Name
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3 py-2 border border-slate-600 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-200 mb-1">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="w-full px-3 py-2 border border-slate-600 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-200 mb-1">
                  Sourcing Type
                </label>
                <select
                  value={sourcing}
                  onChange={(e) => setSourcing(e.target.value as any)}
                  className="w-full px-3 py-2 border border-slate-600 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  <option value="internal">Internal</option>
                  <option value="external">External</option>
                </select>
              </div>
            </div>
          ) : (
            <div>
              <h2 className="text-2xl font-bold text-slate-100 mb-2">{name}</h2>
              <p className="text-slate-300 mb-4">{description}</p>
              <div className="flex gap-4">
                <div>
                  <p className="text-sm text-slate-400">Sourcing</p>
                  <p className="text-sm font-medium text-slate-100 capitalize">
                    {article.sourcing_type}
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>

        <button
          onClick={() => (isEditing ? handleSave() : setIsEditing(true))}
          disabled={updateArticle.isPending}
          className="ml-4 px-3 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 text-sm font-medium"
        >
          {isEditing ? 'Save' : 'Edit'}
        </button>
        {isEditing && (
          <button
            onClick={() => {
              setIsEditing(false);
              setName(article.name);
              setDescription(article.description || '');
              setSourcing(article.sourcing_type);
            }}
            className="ml-2 px-3 py-2 bg-slate-700 text-slate-100 rounded-md hover:bg-slate-600 text-sm font-medium"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
