import { useState } from 'react'
import { SceneNode } from '../hooks/useGLTFLoader'

interface ObjectTreeProps {
  tree: SceneNode | null
  onSelectNode?: (node: SceneNode) => void
  onToggleVisibility?: (node: SceneNode) => void
  selectedNodeId?: string | null
}

interface ObjectTreeNodeProps {
  node: SceneNode
  onSelectNode?: (node: SceneNode) => void
  onToggleVisibility?: (node: SceneNode) => void
  selectedNodeId?: string | null
  level?: number
}

function getNodeIcon(type: SceneNode['type']): string {
  switch (type) {
    case 'mesh':
      return '▮'
    case 'group':
      return '📦'
    case 'light':
      return '💡'
    case 'camera':
      return '📷'
    case 'bone':
      return '🦴'
    default:
      return '○'
  }
}

function ObjectTreeNode({
  node,
  onSelectNode,
  onToggleVisibility,
  selectedNodeId,
  level = 0
}: ObjectTreeNodeProps) {
  const [expanded, setExpanded] = useState(true)
  const hasChildren = node.children.length > 0
  const isSelected = selectedNodeId === node.id

  const handleToggleVisibility = (e: React.MouseEvent) => {
    e.stopPropagation()
    onToggleVisibility?.(node)
    // Also toggle visibility on the Three.js object
    node.object.visible = !node.object.visible
  }

  const handleSelect = () => {
    onSelectNode?.(node)
  }

  return (
    <div>
      <div
        className={`flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-gray-200 dark:hover:bg-gray-700 rounded ${
          isSelected ? 'bg-blue-100 dark:bg-blue-900/30 border-l-2 border-blue-600 dark:border-blue-500' : ''
        }`}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        onClick={handleSelect}
      >
        {/* Expand/Collapse Toggle */}
        {hasChildren && (
          <button
            onClick={(e) => {
              e.stopPropagation()
              setExpanded(!expanded)
            }}
            className="w-5 h-5 flex items-center justify-center text-gray-600 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200 text-sm"
          >
            {expanded ? '▼' : '▶'}
          </button>
        )}
        {!hasChildren && <div className="w-5" />}

        {/* Node Icon */}
        <span className="w-4 text-center">{getNodeIcon(node.type)}</span>

        {/* Node Name */}
        <span className="flex-1 text-sm text-gray-700 dark:text-gray-300 font-medium truncate">
          {node.name}
        </span>

        {/* Visibility Toggle */}
        <button
          onClick={handleToggleVisibility}
          className="w-5 h-5 flex items-center justify-center text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300"
          title={node.object.visible ? 'Hide' : 'Show'}
        >
          {node.object.visible ? '👁' : '🚫'}
        </button>
      </div>

      {/* Children */}
      {expanded && hasChildren && (
        <div>
          {node.children.map((child: SceneNode) => (
            <ObjectTreeNode
              key={child.id}
              node={child}
              onSelectNode={onSelectNode}
              onToggleVisibility={onToggleVisibility}
              selectedNodeId={selectedNodeId}
              level={level + 1}
            />
          ))}
        </div>
      )}
    </div>
  )
}

export function ObjectTree({
  tree,
  onSelectNode,
  onToggleVisibility,
  selectedNodeId
}: ObjectTreeProps) {
  if (!tree) {
    return (
      <div className="p-4 text-sm text-gray-500 dark:text-gray-400">
        No model loaded
      </div>
    )
  }

  return (
    <div className="overflow-y-auto bg-gray-50 dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700">
      <div className="p-2">
        <ObjectTreeNode
          node={tree}
          onSelectNode={onSelectNode}
          onToggleVisibility={onToggleVisibility}
          selectedNodeId={selectedNodeId}
          level={0}
        />
      </div>
    </div>
  )
}
