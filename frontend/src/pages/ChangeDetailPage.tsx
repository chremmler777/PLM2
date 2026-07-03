import { useParams, useSearchParams } from 'react-router-dom';
import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { changesApi } from '../api/changes';
import { plantsApi } from '../api/plants';
import AssessmentRouting from '../components/changes/AssessmentRouting';
import D1MasterPanel from '../components/changes/D1MasterPanel';
import SummationView from '../components/changes/SummationView';
import CostLineGrid from '../components/changes/CostLineGrid';
import DeviationBanner from '../components/changes/DeviationBanner';
import ReasonDialog from '../components/changes/ReasonDialog';
import ImpactTree from '../components/changes/ImpactTree';
import ImplementationPanel from '../components/changes/ImplementationPanel';
import LifecycleStepper from '../components/changes/LifecycleStepper';
import CockpitSummary from '../components/changes/CockpitSummary';
import { DeadlineChip } from '../components/changes/DeadlineChip';
import AuditTimeline from '../components/changes/AuditTimeline';
import { useDepartments } from '../hooks/queries/useWorkflows';
import { t } from '../i18n/cmLabels';
import { STATUS_LABELS } from '../lib/changeStatus';

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

type Tab = 'overview' | 'impacted' | 'implementation' | 'assessments' | 'commercial' | 'd1' | 'audit';
const TABS: Tab[] = ['overview', 'impacted', 'implementation', 'assessments', 'commercial', 'd1', 'audit'];

export default function ChangeDetailPage() {
  const { id } = useParams();
  const changeId = Number(id);
  const qc = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get('tab');
  const tab: Tab = TABS.includes(rawTab as Tab) ? (rawTab as Tab) : 'overview';
  const setTab = (t: Tab) => setSearchParams(t === 'overview' ? {} : { tab: t }, { replace: true });
  const [blocked, setBlocked] = useState<{ to: string; reason: string } | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);

  const { data: change, isLoading } = useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId),
  });
  const { data: allPlants = [] } = useQuery({
    queryKey: ['plants'],
    queryFn: plantsApi.list,
  });
  const { data: impl } = useQuery({
    queryKey: ['change', changeId, 'implementation'],
    queryFn: () => changesApi.getImplementation(changeId),
    enabled: !!change && ['in_implementation', 'in_validation', 'released'].includes(change.status),
  });
  const { data: gates = [] } = useQuery({
    queryKey: ['change', changeId, 'gates'],
    queryFn: () => changesApi.getGates(changeId),
  });
  const { data: deviations = [] } = useQuery({
    queryKey: ['change', changeId, 'deviations'],
    queryFn: () => changesApi.listDeviations(changeId),
  });
  const { data: departments = [] } = useDepartments();
  const pendingDeviations = deviations.filter((d) => d.status === 'pending').length;
  const deptName = (id: number) => departments.find((d) => d.id === id)?.name ?? '#' + id;

  const transition = useMutation({
    mutationFn: (vars: { to: string; cancellation_reason?: string }) =>
      changesApi.transition(changeId, vars.to, vars),
    onSuccess: () => {
      setBlocked(null);
      qc.invalidateQueries({ queryKey: ['change', changeId] });
    },
    onError: (e: unknown, vars) => {
      const detail = errDetail(e) ?? 'Transition failed';
      if (vars.to !== 'cancelled') setBlocked({ to: vars.to, reason: detail });
      else toast.error(detail);
    },
  });
  const signOff = useMutation({
    mutationFn: (role: 'pm' | 'quality') => changesApi.signOff(changeId, role),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId] }),
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Sign-off failed'),
  });
  const customer = useMutation({
    mutationFn: (response: string) => changesApi.customerResponse(changeId, response),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId] }),
  });
  const [deadlineDate, setDeadlineDate] = useState('');
  const [deadlineReason, setDeadlineReason] = useState('');
  const deadline = useMutation({
    mutationFn: (vars: { required_by_date: string | null; required_by_reason: string | null }) =>
      changesApi.update(changeId, vars),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['change', changeId] });
      toast.success('Deadline saved');
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Failed to save deadline'),
  });

  useEffect(() => {
    if (change) {
      setDeadlineDate(change.required_by_date ? change.required_by_date.slice(0, 10) : '');
      setDeadlineReason(change.required_by_reason ?? '');
    }
  }, [change?.id, change?.required_by_date, change?.required_by_reason]);

  if (isLoading || !change) return <div className="p-6 text-gray-500">Loading…</div>;

  const advance = (to: string) => {
    if (to === 'cancelled') { setCancelOpen(true); return; }
    transition.mutate({ to });
  };

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold flex items-center gap-3">
          <span>
            <span className="font-mono text-gray-500">{change.change_number}</span> — {change.title}
          </span>
          {impl?.ready_to_go && (
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-green-900 text-green-100">
              ✓ {t('impl.readyToGo')}
            </span>
          )}
        </h1>
        <div className="flex gap-2">
          {change.status === 'on_hold' && (
            <button className="px-3 py-1.5 text-sm border border-slate-600 rounded-lg text-slate-200 hover:bg-slate-700"
                    onClick={() => advance('in_assessment')}>Resume</button>
          )}
          <button className="px-3 py-1.5 text-sm border rounded-lg text-red-600"
                  onClick={() => advance('cancelled')}>Cancel</button>
        </div>
      </div>

      <LifecycleStepper status={change.status} />

      {blocked && (
        <DeviationBanner
          changeId={changeId}
          blockedTo={blocked.to}
          blockedReason={blocked.reason}
          onRetry={() => transition.mutate({ to: blocked.to })}
          onClose={() => setBlocked(null)}
        />
      )}
      <ReasonDialog
        open={cancelOpen}
        title="Cancel change"
        label="Cancellation reason (required, audited)"
        submitLabel="Cancel change"
        onSubmit={(reason) => { setCancelOpen(false); transition.mutate({ to: 'cancelled', cancellation_reason: reason }); }}
        onClose={() => setCancelOpen(false)}
      />

      <CockpitSummary
        change={change}
        gates={gates}
        pendingDeviations={pendingDeviations}
        impl={impl}
        onAdvance={advance}
        advancing={transition.isPending}
        onResolveGate={() => setTab('d1')}
      />

      <div className="border-b flex gap-4 text-sm mb-4">
        {TABS.map((tb) => (
          <button key={tb}
            className={`pb-2 ${tab === tb ? 'border-b-2 border-blue-600 font-medium' : 'text-gray-500'}`}
            onClick={() => setTab(tb)}>
            {tb === 'implementation' ? t('impl.title') : tb[0].toUpperCase() + tb.slice(1)}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <div className="space-y-2 text-sm">
          <p><span className="text-gray-500">Type:</span> {change.change_type}</p>
          <p><span className="text-gray-500">Priority:</span> {change.priority}</p>
          <p><span className="text-gray-500">Status:</span> {STATUS_LABELS[change.status] ?? change.status}</p>
          <p><span className="text-gray-500">Reason:</span> {change.reason ?? '—'}</p>

          <div className="pt-3 border-t border-slate-700 mt-3">
            <h3 className="text-xs uppercase tracking-wide text-slate-500 mb-2 flex items-center gap-2">
              {t('deadline.title')}
              <DeadlineChip date={change.required_by_date} state={change.deadline_state} />
            </h3>
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">{t('deadline.title')}</label>
                <input type="date" value={deadlineDate}
                  onChange={(e) => setDeadlineDate(e.target.value)}
                  className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
              </div>
              <div className="flex-1 min-w-[12rem]">
                <label className="block text-xs text-slate-500 mb-1">{t('deadline.reason')}</label>
                <input type="text" value={deadlineReason}
                  onChange={(e) => setDeadlineReason(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-1.5 text-sm text-slate-100" />
              </div>
              <button
                className="bg-sky-600 hover:bg-sky-500 text-white font-semibold px-4 py-1.5 rounded-lg text-sm disabled:opacity-50"
                disabled={deadline.isPending}
                onClick={() => deadline.mutate({
                  required_by_date: deadlineDate ? new Date(deadlineDate).toISOString() : null,
                  required_by_reason: deadlineReason || null,
                })}>
                {t('deadline.set')}
              </button>
            </div>
          </div>

          <div className="pt-3">
            <label className="text-sm text-gray-500">Attach document (PPT, PDF, …)</label>
            <input type="file" className="block mt-1 text-sm"
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) { await changesApi.uploadAttachment(changeId, f);
                         qc.invalidateQueries({ queryKey: ['change', changeId] }); }
              }} />
            <ul className="mt-2 text-sm">
              {change.attachments.map((a) => <li key={a.id}>📎 {a.filename}</li>)}
            </ul>
          </div>
        </div>
      )}

      {tab === 'impacted' && change && (
        <ImpactTree changeId={change.id} status={change.status} />
      )}

      {tab === 'implementation' && change && (
        <ImplementationPanel changeId={change.id} />
      )}

      {tab === 'assessments' && (
        <div className="space-y-4">
          <AssessmentRouting changeId={changeId} />
          <ul className="text-sm divide-y border rounded-lg">
          {change.assessments.map((a) => (
            <li key={a.id} className="px-4 py-2 flex justify-between items-center gap-3">
              <span>{deptName(a.department_id)}</span>
              <span className="flex items-center gap-3">
                <span className={a.verdict === 'not_feasible' ? 'text-red-600' : ''}>{a.verdict}</span>
                <span className="text-slate-400 text-xs">
                  {a.owner_name ?? t('tasks.unclaimed')}
                  {a.overdue && <span className="text-red-400 ml-2">⚠ {t('tasks.overdue')}</span>}
                </span>
              </span>
            </li>
          ))}
          {change.assessments.length === 0 && <li className="px-4 py-3 text-gray-400">No assessments.</li>}
          </ul>
          {change.assessments.map((a) => (
            <div key={a.id}>
              <div className="text-xs text-slate-400 mb-1">Cost lines — {deptName(a.department_id)}</div>
              <CostLineGrid
                changeId={changeId}
                assessmentId={a.id}
                departmentId={a.department_id}
                plants={
                  (change.affected_plant_ids && change.affected_plant_ids.length > 0
                    ? allPlants.filter((p) => change.affected_plant_ids!.includes(p.id))
                    : allPlants
                  ).map((p) => ({ id: p.id, name: p.name }))
                }
              />
            </div>
          ))}
        </div>
      )}

      {tab === 'd1' && (
        <div className="space-y-4">
          <D1MasterPanel changeId={changeId} />
          <SummationView changeId={changeId} />
        </div>
      )}

      {tab === 'commercial' && (
        <div className="space-y-3 text-sm">
          <p><span className="text-gray-500">Quoted price:</span> {change.quoted_price ?? '—'}</p>
          <p><span className="text-gray-500">Customer response:</span> {change.customer_response}</p>
          <div className="flex gap-2">
            <button className="px-3 py-1.5 border rounded-lg" onClick={() => customer.mutate('accepted')}>Customer accepted</button>
            <button className="px-3 py-1.5 border rounded-lg" onClick={() => customer.mutate('declined')}>Customer declined</button>
          </div>
          <div className="flex gap-2 pt-2">
            <button className="px-3 py-1.5 border rounded-lg" onClick={() => signOff.mutate('pm')}>
              PM sign-off {change.pm_signed_by ? '✓' : ''}
            </button>
            <button className="px-3 py-1.5 border rounded-lg" onClick={() => signOff.mutate('quality')}>
              Quality sign-off {change.quality_signed_by ? '✓' : ''}
            </button>
          </div>
          <p className="text-xs text-gray-400">Approve requires customer acceptance + both sign-offs.</p>
        </div>
      )}

      {tab === 'audit' && (
        <AuditTimeline correlationId={change.change_number} />
      )}
    </div>
  );
}
