import { useParams, useSearchParams } from 'react-router-dom';
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../api/client';
import { changesApi } from '../api/changes';
import { plantsApi } from '../api/plants';
import AssessmentRouting from '../components/changes/AssessmentRouting';
import AssessmentSubmitForm from '../components/changes/AssessmentSubmitForm';
import D1MasterPanel from '../components/changes/D1MasterPanel';
import SummationView from '../components/changes/SummationView';
import CostLineGrid from '../components/changes/CostLineGrid';
import DeviationBanner from '../components/changes/DeviationBanner';
import ReasonDialog from '../components/changes/ReasonDialog';
import ImpactTree from '../components/changes/ImpactTree';
import ImplementationPanel from '../components/changes/ImplementationPanel';
import LifecycleStepper from '../components/changes/LifecycleStepper';
import CockpitSummary from '../components/changes/CockpitSummary';
import PnlCard from '../components/changes/PnlCard';
import ScopingPanel from '../components/changes/ScopingPanel';
import AuditTimeline from '../components/changes/AuditTimeline';
import { CustomerRelevantEditor } from '../components/changes/CustomerRelevantEditor';
import { QuotedPriceEditor } from '../components/changes/QuotedPriceEditor';
import { ScopingMappingHint } from '../components/changes/ScopingMappingHint';
import { useDepartments } from '../hooks/queries/useWorkflows';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n/cmLabels';
import { STATUS_LABELS } from '../lib/changeStatus';

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

type Tab = 'overview' | 'scoping' | 'impacted' | 'implementation' | 'assessments' | 'commercial' | 'd1' | 'audit';
const TABS: Tab[] = ['overview', 'scoping', 'impacted', 'implementation', 'assessments', 'commercial', 'd1', 'audit'];
// Everyday tab bar order (Task 6). D1/Audit are "governance" tabs, rendered as a
// separate right-aligned group and gated by authz — see `canSeeGovernance` below.
const EVERYDAY_TABS: Tab[] = ['overview', 'scoping', 'impacted', 'assessments', 'commercial', 'implementation'];
const GOVERNANCE_TABS: Tab[] = ['d1', 'audit'];
// F2: before costing there's no cost basis yet — the commercial tab shows an
// explainer instead of a dead-end disabled control (mirrors PnlCard's hidden
// rule, which hides the P&L card for the same statuses).
const BEFORE_COSTING: string[] = ['captured', 'scoping', 'in_assessment'];

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
  const [openAssessment, setOpenAssessment] = useState<number | null>(null);

  const { data: change, isLoading } = useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId),
  });
  const { data: allPlants = [] } = useQuery({
    queryKey: ['plants'],
    queryFn: plantsApi.list,
  });
  // The change's project plant, used as the preferred default for new cost-line
  // rows (Task 21). '/v1/plants/projects' lists every project across plants.
  const { data: projects = [] } = useQuery<{ id: number; plant_id: number }[]>({
    queryKey: ['projects'],
    queryFn: async () => (await client.get('/v1/plants/projects')).data,
  });
  const projectPlantId = projects.find((p) => p.id === change?.project_id)?.plant_id ?? null;
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
  const { data: myActions } = useQuery({
    queryKey: ['change-my-actions', changeId],
    queryFn: () => changesApi.myActions(changeId),
  });
  const { data: departments = [] } = useDepartments();
  const { isAdmin, userId } = useAuth();
  const pendingDeviations = deviations.filter((d) => d.status === 'pending').length;
  const deptName = (id: number) => departments.find((d) => d.id === id)?.name ?? '#' + id;
  // Task 19: client-side mirror of the confirm-impact authz (R&D member or
  // admin) — server enforcement already exists (Task 18); this only decides
  // whether to show the button. Defaults to true until departments/memberships
  // have loaded, so the button doesn't flash-hide.
  const rdDeptId = departments.find((d) => d.name === 'R&D')?.id;
  const canConfirmImpact = !myActions ? true
    : isAdmin || (rdDeptId !== undefined && myActions.memberships.includes(rdDeptId));
  // Task 6: governance tabs (D1, Audit) are only visible/reachable for admin,
  // the change lead, or Quality/Project Manager department members — reusing
  // the myActions/departments data already fetched for this page (no new
  // API calls). Client-side only; server-side enforcement is out of scope here.
  const qualityDeptId = departments.find((d) => d.name === 'Quality')?.id;
  const pmDeptId = departments.find((d) => d.name === 'Project Manager')?.id;
  const isChangeLead = userId != null && change?.lead_id != null && userId === change.lead_id;
  const isGovernanceDept = !!myActions && (
    (qualityDeptId !== undefined && myActions.memberships.includes(qualityDeptId)) ||
    (pmDeptId !== undefined && myActions.memberships.includes(pmDeptId))
  );
  const canSeeGovernance = isAdmin || isChangeLead || isGovernanceDept;
  // F8: the backend enforces "PM and Quality sign-off must be different
  // users" (4-eyes) and 400s if violated. Disable the button in place and
  // name the rule instead of letting the user hit the error after clicking.
  const samePersonBlocksPm = !change?.pm_signed_by
    && !!change?.quality_signed_by && userId != null && userId === change.quality_signed_by;
  const samePersonBlocksQuality = !change?.quality_signed_by
    && !!change?.pm_signed_by && userId != null && userId === change.pm_signed_by;

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
  const internalApprove = useMutation({
    mutationFn: (note?: string) => changesApi.approveInternalCosts(changeId, note),
    onSuccess: () => {
      toast.success(t('internal.approved'))
      qc.invalidateQueries({ queryKey: ['change', changeId] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Approval failed'),
  });
  if (isLoading || !change) return <div className="p-6 text-gray-500">Loading…</div>;

  // An unauthorized deep link into a governance tab (?tab=d1 / ?tab=audit)
  // falls back to overview rather than rendering a blank/forbidden tab.
  const effectiveTab: Tab = GOVERNANCE_TABS.includes(tab) && !canSeeGovernance ? 'overview' : tab;

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

      <LifecycleStepper status={change.status} customerRelevant={change.customer_relevant} />

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
        onShowImpact={() => setTab('impacted')}
        actions={myActions?.actions ?? []}
        onAction={(targetTab) => setTab(targetTab as Tab)}
        canSeeGovernance={canSeeGovernance}
      />

      <div className="border-b border-slate-700 flex items-center gap-4 text-sm mb-4">
        {EVERYDAY_TABS.map((tb) => (
          <button key={tb}
            className={`pb-2 ${effectiveTab === tb ? 'border-b-2 border-sky-400 text-sky-300 font-medium' : 'text-slate-400 hover:text-slate-200'}`}
            onClick={() => setTab(tb)}>
            {tb === 'implementation' ? t('impl.title') : tb === 'scoping' ? t('scoping.title') : tb[0].toUpperCase() + tb.slice(1)}
          </button>
        ))}
        {canSeeGovernance && (
          <>
            <span className="ml-auto text-xs uppercase tracking-wide text-slate-500">Governance</span>
            {GOVERNANCE_TABS.map((tb) => (
              <button key={tb}
                className={`pb-2 ${effectiveTab === tb ? 'border-b-2 border-sky-400 text-sky-300 font-medium' : 'text-slate-400 hover:text-slate-200'}`}
                onClick={() => setTab(tb)}>
                {tb[0].toUpperCase() + tb.slice(1)}
              </button>
            ))}
          </>
        )}
      </div>

      {effectiveTab === 'overview' && (
        <div className="space-y-2 text-sm">
          <p><span className="text-gray-500">Type:</span> {change.change_type}</p>
          <p><span className="text-gray-500">Priority:</span> {change.priority}</p>
          <p><span className="text-gray-500">Status:</span> {STATUS_LABELS[change.status] ?? change.status}</p>
          <p><span className="text-gray-500">Reason:</span> {change.reason ?? '—'}</p>
          <CustomerRelevantEditor change={change} canEdit={isAdmin || isChangeLead} />

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

      {effectiveTab === 'scoping' && change && (
        <ScopingPanel changeId={change.id} status={change.status} />
      )}

      {effectiveTab === 'impacted' && change && (
        <ImpactTree changeId={change.id} status={change.status}
          impactConfirmedByName={change.impact_confirmed_by_name}
          impactConfirmedAt={change.impact_confirmed_at}
          canConfirm={canConfirmImpact} />
      )}

      {effectiveTab === 'implementation' && change && (
        <ImplementationPanel changeId={change.id} />
      )}

      {effectiveTab === 'assessments' && (
        <div className="space-y-4">
          <ScopingMappingHint changeId={changeId} assessments={change.assessments} departments={departments} />
          <AssessmentRouting changeId={changeId} />
          <ul className="text-sm divide-y border rounded-lg">
          {change.assessments.map((a) => (
            <li key={a.id} className="px-4 py-2">
              <div className="flex justify-between items-center gap-3">
                <span>{deptName(a.department_id)}</span>
                <span className="flex items-center gap-3">
                  <span className={a.verdict === 'not_feasible' ? 'text-red-600' : ''}>{a.verdict}</span>
                  <span className="text-slate-400 text-xs">
                    {a.owner_name ?? t('tasks.unclaimed')}
                    {a.overdue && <span className="text-red-400 ml-2">⚠ {t('tasks.overdue')}</span>}
                  </span>
                  {a.status === 'active' && (
                    <button
                      onClick={() => setOpenAssessment(openAssessment === a.id ? null : a.id)}
                      className="text-xs text-sky-400 hover:text-sky-300">
                      {openAssessment === a.id ? t('common.close') : t('assessment.submit')}
                    </button>
                  )}
                </span>
              </div>
              {a.status === 'active' && openAssessment === a.id && (
                <div className="mt-2">
                  <AssessmentSubmitForm
                    changeId={changeId}
                    departmentId={a.department_id}
                    departmentName={deptName(a.department_id)}
                    onDone={() => setOpenAssessment(null)}
                  />
                </div>
              )}
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
                projectPlantId={projectPlantId}
                plants={
                  (change.affected_plant_ids && change.affected_plant_ids.length > 0
                    ? allPlants.filter((p) => change.affected_plant_ids!.includes(p.id))
                    : allPlants
                  )
                    .filter((p) => p.is_active !== false)
                    .map((p) => ({ id: p.id, name: p.name, is_active: p.is_active }))
                }
              />
            </div>
          ))}
        </div>
      )}

      {effectiveTab === 'd1' && (
        <div className="space-y-4">
          <D1MasterPanel changeId={changeId} />
          <SummationView changeId={changeId} />
        </div>
      )}

      {effectiveTab === 'commercial' && (
        <div className="space-y-3 text-sm">
          <PnlCard change={change} />
          {BEFORE_COSTING.includes(change.status) ? (
            <div className="border border-slate-700 bg-slate-800/60 rounded-lg p-4 text-slate-300">
              {change.customer_relevant ? (
                <p>
                  Quotes are entered once the change reaches Costing. Currently in{' '}
                  <strong>{STATUS_LABELS[change.status] ?? change.status}</strong> — departments first
                  assess and cost the change.
                </p>
              ) : (
                <p>
                  Costs are approved once the change reaches Costing. Currently in{' '}
                  <strong>{STATUS_LABELS[change.status] ?? change.status}</strong> — departments first
                  assess and cost the change.
                </p>
              )}
            </div>
          ) : change.customer_relevant ? (
            <>
              <QuotedPriceEditor change={change} />
              <p><span className="text-gray-500">Customer response:</span> {change.customer_response}</p>
              <div className="flex gap-2">
                <button className="px-3 py-1.5 border rounded-lg" onClick={() => customer.mutate('accepted')}>Customer accepted</button>
                <button className="px-3 py-1.5 border rounded-lg" onClick={() => customer.mutate('declined')}>Customer declined</button>
              </div>
              <div className="flex gap-2 pt-2">
                <button className="px-3 py-1.5 border rounded-lg disabled:opacity-50"
                  disabled={!!change.pm_signed_by || samePersonBlocksPm}
                  onClick={() => signOff.mutate('pm')}>
                  PM sign-off {change.pm_signed_by ? '✓' : ''}
                </button>
                <button className="px-3 py-1.5 border rounded-lg disabled:opacity-50"
                  disabled={!!change.quality_signed_by || samePersonBlocksQuality}
                  onClick={() => signOff.mutate('quality')}>
                  Quality sign-off {change.quality_signed_by ? '✓' : ''}
                </button>
              </div>
              {(samePersonBlocksPm || samePersonBlocksQuality) && (
                <p className="text-xs text-amber-300">PM and Quality sign-off must be different users</p>
              )}
              <p className="text-xs text-gray-400">Approve requires customer acceptance + both sign-offs.</p>
            </>
          ) : (
            <div className="space-y-2">
              {change.internal_approved_at ? (
                <div className="border border-emerald-800 bg-emerald-950/40 rounded-lg p-3">
                  <p className="text-emerald-300 font-medium">✓ {t('internal.approved')}</p>
                  <p className="text-xs text-slate-400 mt-1">
                    {t('internal.amount')}: {change.internal_approved_amount?.toFixed(2) ?? '—'}
                    {' · '}{new Date(change.internal_approved_at).toLocaleDateString()}
                  </p>
                  {change.internal_approval_note && (
                    <p className="text-xs text-slate-400">{change.internal_approval_note}</p>
                  )}
                </div>
              ) : (
                <button
                  className="bg-emerald-700 hover:bg-emerald-600 text-white font-semibold px-4 py-2 rounded-lg text-sm disabled:opacity-50"
                  disabled={change.status !== 'costing' || internalApprove.isPending}
                  onClick={() => internalApprove.mutate(undefined)}>
                  {t('internal.approve')}
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {effectiveTab === 'audit' && (
        <AuditTimeline correlationId={change.change_number} />
      )}
    </div>
  );
}
