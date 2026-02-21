/**
 * RevisionTree - Hierarchical revision tree view
 */

import { useState } from 'react';
import { RevisionTreeResponse, RevisionTypeEnum } from '../../types/article';
import { ChevronDownIcon, ChevronRightIcon } from '@heroicons/react/20/solid';

interface Props {
  tree: RevisionTreeResponse;
  selectedRevisionId: number | null;
  onSelectRevision: (revisionId: number) => void;
}

const typeColors = {
  [RevisionTypeEnum.ENGINEERING]: 'text-blue-600',
  [RevisionTypeEnum.RELEASED]: 'text-green-600',
  [RevisionTypeEnum.CHANGE]: 'text-amber-600',
};

const statusColors = {
  draft: 'bg-gray-100 text-gray-800',
  rfq: 'bg-yellow-100 text-yellow-800',
  in_review: 'bg-blue-100 text-blue-800',
  approved: 'bg-green-100 text-green-800',
  in_implementation: 'bg-blue-100 text-blue-800',
  released: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
  canceled: 'bg-gray-100 text-gray-800',
  superseded: 'bg-gray-100 text-gray-800',
};

export default function RevisionTree({ tree, selectedRevisionId, onSelectRevision }: Props) {
  const [expandedIndexes, setExpandedIndexes] = useState<Set<string>>(new Set());

  const toggleExpanded = (key: string) => {
    const newExpanded = new Set(expandedIndexes);
    if (newExpanded.has(key)) {
      newExpanded.delete(key);
    } else {
      newExpanded.add(key);
    }
    setExpandedIndexes(newExpanded);
  };

  return (
    <div className="space-y-4">
      {/* Engineering Revisions */}
      {tree.engineering.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-gray-700 uppercase mb-2 px-2">
            Engineering
          </h4>
          <div className="space-y-1">
            {tree.engineering.map((rev) => (
              <button
                key={rev.id}
                onClick={() => onSelectRevision(rev.id)}
                className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                  selectedRevisionId === rev.id
                    ? 'bg-blue-100 text-blue-900 font-semibold'
                    : 'hover:bg-gray-100'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className={`font-mono font-semibold ${typeColors[RevisionTypeEnum.ENGINEERING]}`}>
                    {rev.revision}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded ${statusColors[rev.status as keyof typeof statusColors]}`}>
                    {rev.status.replace(/_/g, ' ')}
                  </span>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Released Indexes */}
      {tree.released_indexes.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-gray-700 uppercase mb-2 px-2">
            Released
          </h4>
          <div className="space-y-1">
            {tree.released_indexes.map((index) => (
              <div key={index.id}>
                <button
                  onClick={() => onSelectRevision(index.id)}
                  className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                    selectedRevisionId === index.id
                      ? 'bg-blue-100 text-blue-900 font-semibold'
                      : 'hover:bg-gray-100'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className={`font-mono font-semibold ${typeColors[RevisionTypeEnum.RELEASED]}`}>
                      {index.revision}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded ${statusColors[index.status as keyof typeof statusColors]}`}>
                      {index.status.replace(/_/g, ' ')}
                    </span>
                  </div>
                </button>

                {/* Changes to this index */}
                {index.changes.length > 0 && (
                  <div className="ml-4 space-y-1 mt-1">
                    {index.changes.map((change) => (
                      <button
                        key={change.id}
                        onClick={() => onSelectRevision(change.id)}
                        className={`w-full text-left px-3 py-2 rounded-md text-sm transition-colors ${
                          selectedRevisionId === change.id
                            ? 'bg-blue-100 text-blue-900 font-semibold'
                            : 'hover:bg-gray-100'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className={`font-mono font-semibold ${typeColors[RevisionTypeEnum.CHANGE]}`}>
                            {change.revision}
                          </span>
                          <span className={`text-xs px-2 py-0.5 rounded ${statusColors[change.status as keyof typeof statusColors]}`}>
                            {change.status.replace(/_/g, ' ')}
                          </span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {tree.engineering.length === 0 && tree.released_indexes.length === 0 && (
        <p className="text-sm text-gray-500 px-2 py-4">No revisions yet</p>
      )}
    </div>
  );
}
