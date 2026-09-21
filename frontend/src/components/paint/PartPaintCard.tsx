/**
 * PartPaintCard - paint setup for a part: toggle required, process/notes,
 * ordered layers (add/remove/reorder) with a single Save writing the whole
 * setup.
 */
import { useEffect, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { getPartPaint, putPartPaint, listPaints } from '../../api/paints';
import { apiErrorMessage } from '../../lib/apiError';
import { PAINT_TYPE_LABEL, type Paint } from '../../types/paint';
import ColourSwatch from './ColourSwatch';

interface DraftLayer {
  paint_id: number;
  area: string;
  notes: string;
  paint: Paint;
}

export default function PartPaintCard({ partId }: { partId: number }) {
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ['part-paint', partId],
    queryFn: () => getPartPaint(partId),
  });
  const { data: availablePaints } = useQuery({
    queryKey: ['paints', 'active'],
    queryFn: () => listPaints({ activeOnly: true }),
  });

  // The part this draft was hydrated from. Navigating between parts (used-in
  // chips, BOM tree) swaps `partId` in place, so a draft hydrated for the old
  // part must be dropped — otherwise Save would write it to the new part.
  const [hydratedFor, setHydratedFor] = useState<number | null>(null);
  const [paintRequired, setPaintRequired] = useState(false);
  const [process, setProcess] = useState('');
  const [notes, setNotes] = useState('');
  const [layers, setLayers] = useState<DraftLayer[]>([]);
  const [pickerPaintId, setPickerPaintId] = useState('');

  useEffect(() => {
    if (hydratedFor !== null && hydratedFor !== partId) {
      setHydratedFor(null);
      setPaintRequired(false);
      setProcess('');
      setNotes('');
      setLayers([]);
      setPickerPaintId('');
      return;
    }
    if (data && hydratedFor === null) {
      setPaintRequired(data.paint_required);
      setProcess(data.process ?? '');
      setNotes(data.notes ?? '');
      setLayers(
        data.layers.map((l) => ({
          paint_id: l.paint.id,
          area: l.area ?? '',
          notes: l.notes ?? '',
          paint: l.paint,
        }))
      );
      setHydratedFor(partId);
    }
  }, [data, partId, hydratedFor]);

  const save = useMutation({
    mutationFn: () =>
      putPartPaint(partId, {
        paint_required: paintRequired,
        process: paintRequired ? process || null : null,
        notes: paintRequired ? notes || null : null,
        layers: paintRequired
          ? layers.map((l) => ({ paint_id: l.paint_id, area: l.area || null, notes: l.notes || null }))
          : [],
      }),
    onSuccess: () => {
      toast.success('Paint setup saved');
      queryClient.invalidateQueries({ queryKey: ['part-paint', partId] });
      queryClient.invalidateQueries({ queryKey: ['part', partId] });
    },
    onError: (e: unknown) => toast.error(apiErrorMessage(e, 'Could not save the paint setup')),
  });

  const addLayer = () => {
    const paint = availablePaints?.find((p) => p.id === Number(pickerPaintId));
    if (!paint) return;
    setLayers((prev) => [...prev, { paint_id: paint.id, area: '', notes: '', paint }]);
    setPickerPaintId('');
  };

  const moveLayer = (index: number, dir: -1 | 1) => {
    setLayers((prev) => {
      const target = index + dir;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  };

  const removeLayer = (index: number) => {
    setLayers((prev) => prev.filter((_, i) => i !== index));
  };

  const updateLayerArea = (index: number, value: string) => {
    setLayers((prev) => prev.map((l, i) => (i === index ? { ...l, area: value } : l)));
  };

  const missingSpec = paintRequired && layers.length === 0;

  if (hydratedFor === null) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
        <h2 className="text-xl font-bold text-slate-100 mb-4">Paint</h2>
        <p className="text-slate-400 text-sm">Loading…</p>
      </div>
    );
  }

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold text-slate-100">Paint</h2>
        <label className="flex items-center gap-2 text-sm text-slate-200">
          <input
            type="checkbox"
            data-testid="paint-required-toggle"
            checked={paintRequired}
            onChange={(e) => setPaintRequired(e.target.checked)}
          />
          Paint required
        </label>
      </div>

      {missingSpec && <p className="text-amber-400 text-sm mb-4">paint spec missing</p>}

      {paintRequired && (
        <div>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div>
              <label className="text-sm text-slate-400 block mb-1">Process</label>
              <input
                data-testid="paint-process-input"
                value={process}
                onChange={(e) => setProcess(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-100"
              />
            </div>
            <div>
              <label className="text-sm text-slate-400 block mb-1">Notes</label>
              <input
                data-testid="paint-notes-input"
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-100"
              />
            </div>
          </div>

          <div className="space-y-2 mb-4">
            {layers.map((layer, index) => (
              <div
                key={index}
                data-testid={`paint-layer-${index}`}
                className="flex items-center gap-2 bg-slate-900 border border-slate-700 rounded px-3 py-2"
              >
                <ColourSwatch hex={layer.paint.colour_hex} code={layer.paint.colour_code} />
                <span className="text-slate-100 font-medium">{layer.paint.name}</span>
                <span className="text-slate-400 text-sm">{PAINT_TYPE_LABEL[layer.paint.paint_type]}</span>
                {layer.paint.colour_code && <span className="text-slate-400 text-sm">{layer.paint.colour_code}</span>}
                {!layer.paint.is_active && <span className="text-red-400 text-xs">inactive</span>}
                <input
                  data-testid={`paint-layer-area-${index}`}
                  value={layer.area}
                  placeholder="area"
                  maxLength={255}
                  onChange={(e) => updateLayerArea(index, e.target.value)}
                  className="bg-slate-800 border border-slate-700 rounded px-2 py-0.5 text-sm text-slate-100 flex-1"
                />
                <button
                  data-testid={`move-up-${index}`}
                  onClick={() => moveLayer(index, -1)}
                  disabled={index === 0}
                  className="text-slate-300 disabled:text-slate-600"
                >
                  ↑
                </button>
                <button
                  data-testid={`move-down-${index}`}
                  onClick={() => moveLayer(index, 1)}
                  disabled={index === layers.length - 1}
                  className="text-slate-300 disabled:text-slate-600"
                >
                  ↓
                </button>
                <button data-testid={`remove-layer-${index}`} onClick={() => removeLayer(index)} className="text-red-400">
                  Remove
                </button>
              </div>
            ))}
          </div>

          <div className="flex items-center gap-2 mb-4">
            <select
              data-testid="paint-picker"
              value={pickerPaintId}
              onChange={(e) => setPickerPaintId(e.target.value)}
              className="bg-slate-900 border border-slate-700 rounded px-2 py-1 text-slate-100"
            >
              <option value="">Add a paint…</option>
              {availablePaints?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <button
              data-testid="add-layer-button"
              onClick={addLayer}
              disabled={!pickerPaintId}
              className="px-3 py-1 bg-slate-700 text-slate-100 rounded hover:bg-slate-600 text-sm"
            >
              Add layer
            </button>
          </div>
        </div>
      )}

      <button
        data-testid="save-paint"
        onClick={() => save.mutate()}
        disabled={save.isPending}
        className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
      >
        Save
      </button>
    </div>
  );
}
