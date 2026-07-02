import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { changesApi } from '../../api/changes'
import type { ChangeStatus, ImpactTreeNode } from '../../types/change'
import { t } from '../../i18n/cmLabels'

const LOCKED: ChangeStatus[] = [
  'in_implementation', 'in_validation', 'released', 'closed', 'rejected', 'cancelled',
]

interface Props {
  changeId: number
  status: ChangeStatus
}

export default function ImpactTree({ changeId, status }: Props) {
  const qc = useQueryClient()
  const editable = !LOCKED.includes(status)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  const { data, isLoading } = useQuery({
    queryKey: ['change', changeId, 'impact-tree'],
    queryFn: () => changesApi.getImpactTree(changeId),
  })

  useEffect(() => {
    if (data) setSelected(new Set(data.impacted_part_ids))
  }, [data])

  const selectedKey = useMemo(() => [...selected].sort((a, b) => a - b), [selected])

  const { data: suggestion } = useQuery({
    queryKey: ['change', changeId, 'impact-suggest', selectedKey.join(',')],
    queryFn: () => changesApi.suggestImpact(changeId, selectedKey),
    enabled: editable && selectedKey.length > 0,
  })
  const suggested = useMemo(
    () => new Set(suggestion?.suggested_part_ids ?? []), [suggestion])

  const apply = useMutation({
    mutationFn: () => changesApi.applyImpactSelection(changeId, selectedKey),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', changeId] })
      qc.invalidateQueries({ queryKey: ['change', changeId, 'impact-tree'] })
    },
    onError: (e: any) => alert(e?.response?.data?.detail ?? 'Apply failed'),
  })

  const toggle = (partId: number) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(partId)) next.delete(partId)
      else next.add(partId)
      return next
    })
  }

  if (isLoading) return <div className="text-slate-400 text-sm">…</div>
  if (!data || data.tree.length === 0)
    return <div className="text-slate-400 text-sm">{t('impact.empty')}</div>

  const dirty =
    selectedKey.join(',') !== [...data.impacted_part_ids].sort((a, b) => a - b).join(',')

  const renderNode = (node: ImpactTreeNode, depth: number) => (
    <div key={node.part_id}>
      <div
        className="flex items-center gap-2 py-1 rounded hover:bg-slate-700/40"
        style={{ paddingLeft: `${depth * 20}px` }}
      >
        <input
          type="checkbox"
          className="accent-sky-500"
          aria-label={`${node.name} (${node.part_number})`}
          checked={selected.has(node.part_id)}
          disabled={!editable || node.is_lead || node.resulting_revision_id !== null}
          onChange={() => toggle(node.part_id)}
        />
        <span className="text-slate-100 text-sm">{node.name}</span>
        <span className="text-slate-500 text-xs">{node.part_number}</span>
        {node.is_lead && (
          <span className="px-2 py-0.5 rounded-full text-xs bg-sky-900 text-sky-100">
            {t('impact.lead')}
          </span>
        )}
        {node.resulting_revision_id !== null && (
          <span className="px-2 py-0.5 rounded-full text-xs bg-purple-900 text-purple-100">
            ECN #{node.resulting_revision_id}
          </span>
        )}
        {!selected.has(node.part_id) && suggested.has(node.part_id) && (
          <button
            onClick={() => editable && toggle(node.part_id)}
            className="px-2 py-0.5 rounded-full text-xs bg-amber-900 text-amber-100 hover:bg-amber-800"
            title={t('impact.hint')}
          >
            {t('impact.suggested')} +
          </button>
        )}
      </div>
      {node.children.map(c => renderNode(c, depth + 1))}
    </div>
  )

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-slate-100 font-semibold">{t('impact.title')}</h3>
          <p className="text-slate-400 text-xs">{t('impact.hint')}</p>
        </div>
        {editable ? (
          <button
            onClick={() => apply.mutate()}
            disabled={!dirty || apply.isPending}
            className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm disabled:opacity-50"
          >
            {t('impact.apply')}
          </button>
        ) : (
          <span className="text-amber-300 text-xs">{t('impact.locked')}</span>
        )}
      </div>
      {data.tree.map(n => renderNode(n, 0))}
    </div>
  )
}
