/** A material as shown on the article and in the worksheet: a MaterialDB link, or the text with a NEW badge. */
import { materialDbUrl, type PartMaterial } from '../../api/materials';
import { NEW_MATERIAL_BADGE } from '../../lib/material';

export default function MaterialValue({ material, testId }: { material: PartMaterial; testId?: string }) {
  if (material.material_source === 'materialdb' && material.materialdb_id != null) {
    return (
      <a data-testid={testId} href={materialDbUrl(material.materialdb_id)} target="_blank" rel="noreferrer"
        title="Open in MaterialDB" className="text-sky-300 hover:underline">
        {material.material_label ?? `MaterialDB #${material.materialdb_id}`}
      </a>
    );
  }
  if (material.material_source === 'new') {
    return (
      <span data-testid={testId} className="inline-flex items-center gap-1.5">
        <span className="text-slate-100">{material.material_new_text}</span>
        <span data-testid={testId ? `${testId}-new` : undefined}
          className="px-1.5 py-0.5 rounded bg-amber-900/60 text-amber-300 text-[10px] font-semibold uppercase whitespace-nowrap">
          {NEW_MATERIAL_BADGE}
        </span>
      </span>
    );
  }
  return <span data-testid={testId} className="text-slate-500">not set</span>;
}
