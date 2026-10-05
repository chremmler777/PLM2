/**
 * ToolShrinkCard - the shrinkage the tool steel is cut with, as a decision record:
 * the candidates MaterialDB holds for the produced articles' materials (datasheet,
 * supplier statement, KTX tool experience), each with its source; the decision with
 * its source and reason; after the trial the measured shrinkage and a verdict, which
 * is reported back to MaterialDB for the next tool. Values only change through a
 * decision, so every value on a tool says where it came from.
 */
import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  decideShrinkage, fetchToolShrinkage, reportShrinkage, verifyShrinkage,
  type ShrinkCandidate, type ShrinkDecision, type ShrinkSourceKind, type ShrinkVerdict,
} from '../../api/toolShrink';
import { apiErrorMessage } from '../../lib/apiError';
import { formatDate, numberEditText, parseNumberInput } from '../../lib/format';
import { usePartFieldNoteIndex } from '../../hooks/queries/useFieldNotes';
import FieldNoteMarker from '../fieldNotes/FieldNoteMarker';

const KIND: Record<ShrinkSourceKind, string> = {
  supplier: 'Supplier statement',
  ktx_experience: 'KTX tool experience',
  datasheet: 'Datasheet',
  own: 'Own value',
};

const VERDICT: Record<ShrinkVerdict, { label: string; cls: string }> = {
  correct: { label: 'Correct', cls: 'bg-emerald-900/60 text-emerald-200' },
  offset: { label: 'Needs offset', cls: 'bg-amber-900/60 text-amber-200' },
  wrong: { label: 'Wrong', cls: 'bg-red-900/60 text-red-200' },
};

const FIBRE = new Set(['GF', 'CF', 'GB']);

const input = 'bg-slate-900 border border-slate-600 rounded px-2 py-1 text-slate-100 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500';
const btnPrimary = 'text-sm px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white';
const btnQuiet = 'text-sm px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-100';

const pct = (a: number | null | undefined, b: number | null | undefined) =>
  a == null && b == null ? '-' : a === b ? `${a} %` : `${a ?? '-'} / ${b ?? '-'} %`;

/** Either one combined value or parallel / normal. */
const valuesText = (combined: number | null | undefined, a: number | null | undefined, b: number | null | undefined) =>
  combined != null ? `${combined} % combined` : a == null && b == null ? '-' : `${a ?? '-'} / ${b ?? '-'} % parallel / normal`;

const FIELD_KEYS = ['tool.shrink_combined', 'tool.shrink_parallel', 'tool.shrink_normal'] as const;

/** Either one combined value or parallel + normal, never both. */
function ModeSwitch({ combined, onChange }: { combined: boolean; onChange(combined: boolean): void }) {
  return (
    <fieldset className="text-sm">
      <legend className="text-slate-400">Value</legend>
      <div role="radiogroup" className="mt-1 inline-flex rounded border border-slate-600 overflow-hidden">
        {([[true, 'Combined'], [false, 'Parallel / normal']] as const).map(([v, label]) => (
          <label key={label} className={`px-3 py-1 cursor-pointer ${combined === v
            ? 'bg-slate-600 text-slate-100' : 'text-slate-300 hover:bg-slate-700'}`}>
            <input type="radio" className="sr-only" checked={combined === v} onChange={() => onChange(v)}
              data-testid={v ? 'shrink-mode-combined' : 'shrink-mode-split'} />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

interface Draft {
  combined: boolean;
  parallel: string;
  normal: string;
  kind: ShrinkSourceKind;
  source: string;
  rationale: string;
  materialdb_id: number | null;
  material_label: string | null;
}

interface VerifyDraft {
  combined: boolean;
  parallel: string;
  normal: string;
  ref: string;
  verdict: ShrinkVerdict | null;
  note: string;
}

export default function ToolShrinkCard({ partId, projectId = null }: { partId: number; projectId?: number | null }) {
  const qc = useQueryClient();
  const notes = usePartFieldNoteIndex(partId);
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['tool-shrinkage', partId],
    queryFn: () => fetchToolShrinkage(partId),
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [verifyDraft, setVerifyDraft] = useState<VerifyDraft | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['tool-shrinkage', partId] });
    qc.invalidateQueries({ queryKey: ['part'] });
    qc.invalidateQueries({ queryKey: ['parts'] });
    qc.invalidateQueries({ queryKey: ['project-parts'] });
  };

  const decide = useMutation({
    mutationFn: (d: Draft) => decideShrinkage(partId, {
      combined_pct: d.combined ? parseNumberInput(d.parallel) : null,
      parallel_pct: d.combined ? null : parseNumberInput(d.parallel),
      normal_pct: d.combined ? null : parseNumberInput(d.normal),
      source_kind: d.kind, source_label: d.source.trim() || null, rationale: d.rationale.trim(),
      materialdb_id: d.materialdb_id, material_label: d.material_label, candidates: data?.candidates ?? [],
    }),
    onSuccess: () => { toast.success('Shrinkage decision saved'); setDraft(null); refresh(); },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not save the decision')),
  });

  const verify = useMutation({
    mutationFn: ({ id, v }: { id: number; v: VerifyDraft }) => verifyShrinkage(partId, id, {
      measured_combined_pct: v.combined ? parseNumberInput(v.parallel) : null,
      measured_parallel_pct: v.combined ? null : parseNumberInput(v.parallel),
      measured_normal_pct: v.combined ? null : parseNumberInput(v.normal),
      measured_ref: v.ref.trim(), verdict: v.verdict as ShrinkVerdict, next_time_note: v.note.trim() || null,
    }),
    onSuccess: (res: { decisions: ShrinkDecision[] }) => {
      const fb = res.decisions.find((d) => d.status === 'current')?.feedback_status;
      if (fb === 'failed') toast.warning('Verification saved, but MaterialDB could not be reached. Send it again later.');
      else toast.success(fb === 'sent' ? 'Verification saved and sent to MaterialDB' : 'Verification saved');
      setVerifyDraft(null);
      refresh();
    },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not save the verification')),
  });

  const resend = useMutation({
    mutationFn: (id: number) => reportShrinkage(partId, id),
    onSuccess: () => { toast.success('Sent to MaterialDB'); refresh(); },
    onError: (e) => toast.error(apiErrorMessage(e, 'Could not send to MaterialDB')),
  });

  if (isLoading) {
    return <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8 text-slate-400 text-sm">Loading shrinkage…</div>;
  }
  if (isError || !data) {
    return (
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8 text-sm text-red-300">
        {apiErrorMessage(error, 'Could not load the shrinkage of this tool')}
      </div>
    );
  }

  const current = data.decisions.find((d) => d.status === 'current') ?? null;
  const past = data.decisions.filter((d) => d.status !== 'current');
  const combinedNow = data.tool.combined_pct != null;
  const unrecorded = !current && (combinedNow || data.tool.parallel_pct != null || data.tool.normal_pct != null);
  const fibre = data.materials.some((m) => m.filler_type && FIBRE.has(m.filler_type.toUpperCase()));

  const startFrom = (c: ShrinkCandidate | null) => setDraft(c ? {
    combined: !fibre && c.parallel_pct === (c.normal_pct ?? c.parallel_pct),
    parallel: numberEditText(c.parallel_pct ?? c.normal_pct), normal: numberEditText(c.normal_pct ?? c.parallel_pct),
    kind: c.kind, source: c.source_label, rationale: '', materialdb_id: c.materialdb_id, material_label: c.material_label,
  } : {
    combined: combinedNow || (!fibre && data.tool.parallel_pct == null && data.tool.normal_pct == null),
    parallel: numberEditText(data.tool.combined_pct ?? data.tool.parallel_pct), normal: numberEditText(data.tool.normal_pct),
    kind: 'own', source: '', rationale: '',
    materialdb_id: data.materials[0]?.materialdb_id ?? null, material_label: data.materials[0]?.label ?? null,
  });

  const draftValid = draft != null && parseNumberInput(draft.parallel) != null
    && (draft.combined || parseNumberInput(draft.normal) != null)
    && draft.rationale.trim() !== '' && (draft.kind === 'own' || draft.source.trim() !== '');
  const splitOnUnfilled = draft != null && !draft.combined && !fibre && data.materials.length > 0
    && parseNumberInput(draft.parallel) != null && parseNumberInput(draft.parallel) !== parseNumberInput(draft.normal);

  const verifyValid = verifyDraft != null && verifyDraft.verdict != null && verifyDraft.ref.trim() !== ''
    && (parseNumberInput(verifyDraft.parallel) != null || (!verifyDraft.combined && parseNumberInput(verifyDraft.normal) != null))
    && (verifyDraft.verdict === 'correct' || verifyDraft.note.trim() !== '');

  return (
    <section data-testid="tool-shrinkage" className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
      <div className="flex items-start justify-between gap-4 mb-1">
        <div>
          <h2 className="text-xl font-bold text-slate-100">Shrinkage</h2>
          <p className="text-sm text-slate-400">Parallel / normal to the flow, or one combined value, as the steel is cut. Every value records its source and why it was chosen.</p>
        </div>
        <div className="shrink-0 flex items-start gap-6">
          {(combinedNow
            ? [['combined', 'Combined', data.tool.combined_pct]] as const
            : [['parallel', 'Parallel', data.tool.parallel_pct], ['normal', 'Normal', data.tool.normal_pct]] as const
          ).map(([dir, label, v]) => (
            <div key={dir} data-field-key={`tool.shrink_${dir}`} className="text-right">
              <div className="text-sm text-slate-400">
                {label}
                <FieldNoteMarker partId={partId} fieldKey={`tool.shrink_${dir}`} label={`Shrinkage ${dir}`}
                  note={notes.get(`tool.shrink_${dir}`)} projectId={projectId} />
              </div>
              <div data-testid={`shrink-current-${dir}`} className="text-2xl font-semibold text-slate-100 tabular-nums">
                {v == null ? '-' : `${v} %`}
              </div>
            </div>
          ))}
          {/* the worksheet's Edit on the other columns lands here too */}
          {FIELD_KEYS.filter((k) => combinedNow ? k !== 'tool.shrink_combined' : k === 'tool.shrink_combined').map((k) => (
            <span key={k} data-field-key={k} className="sr-only">{k}</span>
          ))}
          {current?.verdict && (
            <span className={`self-center text-xs px-2 py-0.5 rounded ${VERDICT[current.verdict].cls}`}>{VERDICT[current.verdict].label}</span>
          )}
        </div>
      </div>

      {unrecorded && (
        <p data-testid="shrink-unrecorded" className="mt-3 text-sm text-amber-300">
          These values were entered without a recorded source. Record the decision so the next tool knows where they came from.
        </p>
      )}

      {/* Current decision */}
      {current && (
        <div className="mt-4 rounded-md bg-slate-900/60 p-4">
          <div className="grid gap-x-6 gap-y-2 md:grid-cols-[max-content_1fr] text-sm">
            <span className="text-slate-400">Source</span>
            <span className="text-slate-100">
              {KIND[current.source_kind]}{current.source_label ? `: ${current.source_label}` : ''}
              {current.material_label && <span className="text-slate-400"> · {current.material_label}</span>}
            </span>
            <span className="text-slate-400">Why</span>
            <span className="text-slate-100 whitespace-pre-line">{current.rationale}</span>
            <span className="text-slate-400">Decided</span>
            <span className="text-slate-300">{current.decided_by ?? '-'}, {formatDate(current.decided_at)}</span>
            {current.verified_at && (<>
              <span className="text-slate-400">Measured</span>
              <span className="text-slate-100 tabular-nums">
                {valuesText(current.measured_combined_pct, current.measured_parallel_pct, current.measured_normal_pct)}
                <span className="text-slate-400"> · {current.measured_ref} · {current.verified_by}, {formatDate(current.verified_at)}</span>
              </span>
              {current.next_time_note && (<>
                <span className="text-slate-400">Next tool</span>
                <span className="text-slate-100">{current.next_time_note}</span>
              </>)}
              <span className="text-slate-400">MaterialDB</span>
              <span data-testid="shrink-feedback" className="text-slate-300">
                {current.feedback_status === 'sent' && 'Reported to the material'}
                {current.feedback_status === 'skipped' && 'Not reported: no MaterialDB material on this decision'}
                {current.feedback_status === 'failed' && (
                  <span className="text-amber-300">
                    Not reported ({current.feedback_error}){' '}
                    <button onClick={() => resend.mutate(current.id)} disabled={resend.isPending}
                      className="underline underline-offset-2 hover:text-amber-100">Send again</button>
                  </span>
                )}
              </span>
            </>)}
          </div>

          {!verifyDraft && (
            <div className="mt-4 flex gap-2">
              <button data-testid="shrink-verify-open" className={current.verified_at ? btnQuiet : btnPrimary}
                onClick={() => setVerifyDraft({
                  combined: current.combined_pct != null,
                  parallel: numberEditText(current.measured_combined_pct ?? current.measured_parallel_pct),
                  normal: numberEditText(current.measured_normal_pct),
                  ref: current.measured_ref ?? '', verdict: current.verdict, note: current.next_time_note ?? '',
                })}>
                {current.verified_at ? 'Edit verification' : 'Verify after trial'}
              </button>
            </div>
          )}

          {verifyDraft && (
            <form className="mt-4 border-t border-slate-700 pt-4 space-y-3"
              onSubmit={(e) => { e.preventDefault(); if (verifyValid) verify.mutate({ id: current.id, v: verifyDraft }); }}>
              <p className="text-sm text-slate-400">What shrinkage did the parts really show (e.g. from the 6-pc dimensional of TH1/TH2)?</p>
              <div className="flex flex-wrap gap-4">
                <ModeSwitch combined={verifyDraft.combined} onChange={(combined) => setVerifyDraft({ ...verifyDraft, combined })} />
                <label className="text-sm text-slate-400">{verifyDraft.combined ? 'Measured combined (%)' : 'Measured parallel (%)'}
                  <input data-testid="shrink-measured-parallel" inputMode="decimal" value={verifyDraft.parallel}
                    onChange={(e) => setVerifyDraft({ ...verifyDraft, parallel: e.target.value })} className={`${input} block w-28 mt-1`} />
                </label>
                {!verifyDraft.combined && (
                  <label className="text-sm text-slate-400">Measured normal (%)
                    <input data-testid="shrink-measured-normal" inputMode="decimal" value={verifyDraft.normal}
                      onChange={(e) => setVerifyDraft({ ...verifyDraft, normal: e.target.value })} className={`${input} block w-28 mt-1`} />
                  </label>
                )}
                <label className="text-sm text-slate-400 flex-1 min-w-[16rem]">Measurement
                  <input data-testid="shrink-measured-ref" maxLength={300} placeholder="TH1 6-pc CMM report, 10/22/2026"
                    value={verifyDraft.ref} onChange={(e) => setVerifyDraft({ ...verifyDraft, ref: e.target.value })}
                    className={`${input} block w-full mt-1`} />
                </label>
              </div>
              <fieldset>
                <legend className="text-sm text-slate-400 mb-1">Was the chosen value right?</legend>
                <div className="flex flex-wrap gap-2">
                  {(Object.keys(VERDICT) as ShrinkVerdict[]).map((v) => (
                    <label key={v} className={`text-sm px-3 py-1.5 rounded cursor-pointer border ${verifyDraft.verdict === v
                      ? 'border-blue-400 bg-slate-700 text-slate-100' : 'border-slate-600 text-slate-300 hover:bg-slate-700'}`}>
                      <input type="radio" name="verdict" value={v} className="sr-only" checked={verifyDraft.verdict === v}
                        onChange={() => setVerifyDraft({ ...verifyDraft, verdict: v })} />
                      {VERDICT[v].label}
                    </label>
                  ))}
                </div>
              </fieldset>
              <label className="block text-sm text-slate-400">
                Next tool with this material {verifyDraft.verdict && verifyDraft.verdict !== 'correct' ? '(required)' : '(optional)'}
                <textarea data-testid="shrink-next-note" rows={2} maxLength={4000} value={verifyDraft.note}
                  placeholder="e.g. use 0.85 / 1.15 % for 2.5 mm walls, unpainted"
                  onChange={(e) => setVerifyDraft({ ...verifyDraft, note: e.target.value })} className={`${input} block w-full mt-1`} />
              </label>
              <div className="flex gap-2">
                <button type="submit" data-testid="shrink-verify-save" disabled={!verifyValid || verify.isPending} className={btnPrimary}>
                  Save verification
                </button>
                <button type="button" onClick={() => setVerifyDraft(null)} className={btnQuiet}>Cancel</button>
              </div>
            </form>
          )}
        </div>
      )}

      {/* Candidates */}
      <div className="mt-6">
        <div className="flex items-baseline justify-between gap-4 mb-2">
          <h3 className="text-sm font-semibold text-slate-200">
            {current ? 'Other values on record' : 'Values on record'}
          </h3>
          {!draft && (
            <button data-testid="shrink-own" onClick={() => startFrom(null)} className="text-sm text-blue-300 hover:text-blue-200">
              Enter an own value
            </button>
          )}
        </div>
        {data.error && <p className="text-sm text-amber-300 mb-2">MaterialDB: {data.error}. An own value can still be recorded.</p>}
        {data.no_article && <p className="text-sm text-slate-400">No produced article is linked, so there is no material to take values from.</p>}
        {data.no_material && <p className="text-sm text-slate-400">The produced articles have no MaterialDB material linked yet.</p>}
        {!data.error && data.materials.length > 0 && data.candidates.length === 0 && (
          <p className="text-sm text-slate-400">MaterialDB holds no shrinkage for {data.materials.map((m) => m.label).join(', ')}.</p>
        )}
        {data.candidates.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-slate-400 border-b border-slate-700">
                <tr>
                  <th className="text-left font-medium py-1.5 pr-4">Source</th>
                  <th className="text-left font-medium py-1.5 pr-4">Parallel / normal</th>
                  <th className="text-left font-medium py-1.5 pr-4">How it was determined</th>
                  <th className="py-1.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/70 align-top">
                {data.candidates.map((c) => (
                  <tr key={c.key} data-testid="shrink-candidate">
                    <td className="py-2 pr-4">
                      <div className="text-slate-100">{KIND[c.kind]}</div>
                      <div className="text-xs text-slate-400">{c.source_label}{c.doc_date ? ` · ${formatDate(c.doc_date)}` : ''}</div>
                      {data.materials.length > 1 && <div className="text-xs text-slate-500">{c.material_label}</div>}
                    </td>
                    <td className="py-2 pr-4 text-slate-100 tabular-nums whitespace-nowrap">
                      {pct(c.parallel_pct, c.normal_pct)}
                      {c.verdict && <span className={`ml-2 text-xs px-1.5 py-0.5 rounded ${VERDICT[c.verdict].cls}`}>{VERDICT[c.verdict].label}</span>}
                    </td>
                    <td className="py-2 pr-4 text-xs text-slate-400">{[c.method, c.condition].filter(Boolean).join(' · ') || '-'}</td>
                    <td className="py-2 text-right">
                      <button onClick={() => startFrom(c)} disabled={c.parallel_pct == null && c.normal_pct == null}
                        className="text-sm px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 disabled:opacity-40 text-slate-100 whitespace-nowrap">
                        Use this
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data.materials.some((m) => m.notes) && (
          <details className="mt-2 text-xs text-slate-400">
            <summary className="cursor-pointer hover:text-slate-200">Material notes in MaterialDB</summary>
            {data.materials.filter((m) => m.notes).map((m) => (
              <p key={m.materialdb_id} className="mt-1 whitespace-pre-line"><span className="text-slate-300">{m.label}:</span> {m.notes}</p>
            ))}
          </details>
        )}
      </div>

      {/* Decide */}
      {draft && (
        <form data-testid="shrink-decide-form" className="mt-4 rounded-md bg-slate-900/60 p-4 space-y-3"
          onSubmit={(e) => { e.preventDefault(); if (draftValid) decide.mutate(draft); }}>
          <div className="flex flex-wrap gap-4">
            <ModeSwitch combined={draft.combined} onChange={(combined) => setDraft({ ...draft, combined })} />
            <label className="text-sm text-slate-400">{draft.combined ? 'Combined (%)' : 'Parallel (%)'}
              <input data-testid="shrink-parallel" inputMode="decimal" value={draft.parallel}
                onChange={(e) => setDraft({ ...draft, parallel: e.target.value })} className={`${input} block w-28 mt-1`} />
            </label>
            {!draft.combined && (
              <label className="text-sm text-slate-400">Normal (%)
                <input data-testid="shrink-normal" inputMode="decimal" value={draft.normal}
                  onChange={(e) => setDraft({ ...draft, normal: e.target.value })} className={`${input} block w-28 mt-1`} />
              </label>
            )}
            <label className="text-sm text-slate-400">Source
              <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value as ShrinkSourceKind })}
                className={`${input} block mt-1`}>
                {(Object.keys(KIND) as ShrinkSourceKind[]).map((k) => <option key={k} value={k}>{KIND[k]}</option>)}
              </select>
            </label>
            <label className="text-sm text-slate-400 flex-1 min-w-[16rem]">
              {draft.kind === 'own' ? 'Based on (optional)' : 'Document / person'}
              <input data-testid="shrink-source" maxLength={500} value={draft.source}
                placeholder={draft.kind === 'own' ? 'e.g. toolmaker standard' : 'e.g. mail M. Rautzenberg 10/02/2026'}
                onChange={(e) => setDraft({ ...draft, source: e.target.value })} className={`${input} block w-full mt-1`} />
            </label>
          </div>
          {splitOnUnfilled && (
            <p className="text-sm text-amber-300">The material has no glass or carbon fibre: unfilled resins usually get one combined value.</p>
          )}
          <label className="block text-sm text-slate-400">Why this value
            <textarea data-testid="shrink-rationale" rows={2} maxLength={4000} value={draft.rationale}
              placeholder="e.g. supplier measured along/across on a 2.5 mm plaque; our part is 2.5 mm, unpainted"
              onChange={(e) => setDraft({ ...draft, rationale: e.target.value })} className={`${input} block w-full mt-1`} />
          </label>
          <div className="flex items-center gap-2">
            <button type="submit" data-testid="shrink-decide-save" disabled={!draftValid || decide.isPending} className={btnPrimary}>
              {current ? 'Replace the decision' : 'Record the decision'}
            </button>
            <button type="button" onClick={() => setDraft(null)} className={btnQuiet}>Cancel</button>
            {current && <span className="text-xs text-slate-400">The current decision stays in the history.</span>}
          </div>
        </form>
      )}

      {/* History */}
      {past.length > 0 && (
        <div className="mt-6">
          <button onClick={() => setShowHistory(!showHistory)} aria-expanded={showHistory}
            className="text-sm text-slate-400 hover:text-slate-200">
            {showHistory ? 'Hide' : 'Show'} {past.length} earlier {past.length === 1 ? 'decision' : 'decisions'}
          </button>
          {showHistory && (
            <ul className="mt-2 space-y-2 text-sm">
              {past.map((d) => (
                <li key={d.id} className="text-slate-300">
                  <span className="tabular-nums text-slate-100">{valuesText(d.combined_pct, d.parallel_pct, d.normal_pct)}</span>
                  {' '}· {KIND[d.source_kind]}{d.source_label ? `: ${d.source_label}` : ''}
                  <span className="text-slate-400"> · {d.decided_by}, {formatDate(d.decided_at)}</span>
                  <div className="text-xs text-slate-400">{d.rationale}</div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
