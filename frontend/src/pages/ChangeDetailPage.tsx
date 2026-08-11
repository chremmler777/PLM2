import { Link, useParams, useSearchParams } from 'react-router-dom';
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
import ChangeAttachments from '../components/changes/ChangeAttachments';
import { PriorityEditor } from '../components/changes/PriorityEditor';
import AuditTimeline from '../components/changes/AuditTimeline';
import { CustomerRelevantEditor } from '../components/changes/CustomerRelevantEditor';
import { DescriptionEditor } from '../components/changes/DescriptionEditor';
import { QuotedPriceEditor } from '../components/changes/QuotedPriceEditor';
import { ScopingMappingHint } from '../components/changes/ScopingMappingHint';
import ConcernStrip from '../components/changes/ConcernStrip';
import { useDepartments } from '../hooks/queries/useWorkflows';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n/cmLabels';
import { STATUS_LABELS, OFF_PATH_STATUSES } from '../lib/changeStatus';
import { projectLabel } from '../lib/project';
import { CHANGE_STATUS_ORDER, type ChangeStatus } from '../types/change';

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

type Tab = 'overview' | 'scoping' | 'impacted' | 'implementation' | 'assessments' | 'commercial' | 'd1' | 'audit';
const TABS: Tab[] = ['overview', 'scoping', 'impacted', 'implementation', 'assessments', 'commercial', 'd1', 'audit'];
// Everyday tab bar order (Task 6). D1/Audit are "governance" tabs, rendered as a
// separate right-aligned group and gated by authz — see `canSeeGovernance` below.
const EVERYDAY_TABS: Tab[] = ['overview', 'scoping', 'impacted', 'assessments', 'commercial', 'implementation'];
const GOVERNANCE_TABS: Tab[] = ['d1', 'audit'];

// Which tab represents the change's current phase — so the tab bar shows what
// is ACTIVE, not just what the user clicked. Terminal statuses map to nothing.
const STATUS_ACTIVE_TAB: Record<string, Tab> = {
  captured: 'scoping', scoping: 'scoping',
  in_assessment: 'assessments',
  costing: 'commercial', quoted: 'commercial', approved: 'commercial',
  in_implementation: 'implementation', in_validation: 'implementation',
};
// F2: before costing there's no cost basis yet — the commercial tab shows an
// explainer instead of a dead-end disabled control (mirrors PnlCard's hidden
// rule, which hides the P&L card for the same statuses).
const BEFORE_COSTING: string[] = ['captured', 'scoping', 'in_assessment'];
// Each phase-bound tab unlocks when the change reaches its phase: at capture only
// the request itself is on the table (Sales writes it and attaches the evidence),
// scope and affected parts arrive with scoping, costs with costing, and so on. A
// tab with no entry here (overview) is always open; governance tabs keep their
// own authz rule instead.
const TAB_UNLOCK_STATUS: Partial<Record<Tab, ChangeStatus>> = {
  scoping: 'scoping',
  impacted: 'scoping',
  assessments: 'in_assessment',
  commercial: 'costing',
  implementation: 'in_implementation',
};
const phaseIndex = (s: string) => CHANGE_STATUS_ORDER.indexOf(s as ChangeStatus);
const isTabLocked = (status: string, tb: Tab): boolean => {
  const from = TAB_UNLOCK_STATUS[tb];
  if (from === undefined || GOVERNANCE_TABS.includes(tb)) return false;
  // Off-path changes (on_hold/rejected/cancelled) have no place in the order;
  // they have been through the flow, so nothing is withheld from them.
  if (OFF_PATH_STATUSES.includes(status as ChangeStatus)) return false;
  return phaseIndex(status) < phaseIndex(from);
};
// Pre-scoping locks name the phase people are waiting for; later ones are
// generic, since which phase unlocks them is obvious from the tab itself.
const lockedTitleKey = (tb: Tab): string =>
  tb === 'scoping' ? 'tab.scopingHandoff'
  : TAB_UNLOCK_STATUS[tb] === 'scoping' ? 'tab.lockedUntilScoping'
  : 'tab.lockedUntilPhase';

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
  // Rejecting and reopening both stop or restart the flow, so both go through
  // a memo dialog rather than a bare button.
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  const [openAssessment, setOpenAssessment] = useState<number | null>(null);
  // Customer acceptance and internal approval both start the release phase, so
  // both collect a mandatory release deadline through an inline confirm row.
  const [acceptOpen, setAcceptOpen] = useState(false);
  const [acceptDue, setAcceptDue] = useState('');
  const [acceptReason, setAcceptReason] = useState('');
  const [internalOpen, setInternalOpen] = useState(false);
  const [internalDue, setInternalDue] = useState('');

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
  // Client-side mirror of the confirm-impact authz: Development members only —
  // no admin shortcut, because the backend dropped it too (an admin who needs to
  // confirm acts as Development). Defaults to true until departments/memberships
  // have loaded, so the button doesn't flash-disabled.
  const rdDeptId = departments.find((d) => d.name === 'Development')?.id;
  const canConfirmImpact = !myActions ? true
    : rdDeptId !== undefined && myActions.memberships.includes(rdDeptId);
  // Task 6: governance tabs (D1, Audit) are only visible/reachable for admin,
  // the change lead, or Quality/Project Manager department members — reusing
  // the myActions/departments data already fetched for this page (no new
  // API calls). Client-side only; server-side enforcement is out of scope here.
  const qualityDeptId = departments.find((d) => d.name === 'Quality')?.id;
  const pmDeptId = departments.find((d) => d.name === 'Project Manager')?.id;
  const salesDeptId = departments.find((d) => d.name === 'Sales')?.id;
  const isChangeLead = userId != null && change?.lead_id != null && userId === change.lead_id;
  const isQualityMember = !!myActions && qualityDeptId !== undefined
    && myActions.memberships.includes(qualityDeptId);
  const isPmMember = !!myActions && pmDeptId !== undefined
    && myActions.memberships.includes(pmDeptId);
  const isSalesMember = !!myActions && salesDeptId !== undefined
    && myActions.memberships.includes(salesDeptId);
  const isGovernanceDept = isQualityMember || isPmMember;
  const canSeeGovernance = isAdmin || isChangeLead || isGovernanceDept;
  // Governance authz (mirrors the backend 403 gates in change_service.py):
  // sign-off is department-gated with no lead bypass; quoted price and
  // internal-cost approval keep the lead/PM exceptions the backend allows.
  const canSignPm = isAdmin || isPmMember;
  const canSignQuality = isAdmin || isQualityMember;
  const canApproveInternalCosts = isAdmin || isPmMember;
  const canEditQuotedPrice = isAdmin || isChangeLead || isSalesMember;
  // The description is written during capture, and capture is Sales' job — the
  // backend PATCH gate allows lead / Sales / admin, so the editor must too.
  const canEditDescription = isAdmin || isChangeLead || isSalesMember;
  // F8: the backend enforces "PM and Quality sign-off must be different
  // users" (4-eyes) and 400s if violated. Disable the button in place and
  // name the rule instead of letting the user hit the error after clicking.
  const samePersonBlocksPm = !change?.pm_signed_by
    && !!change?.quality_signed_by && userId != null && userId === change.quality_signed_by;
  const samePersonBlocksQuality = !change?.quality_signed_by
    && !!change?.pm_signed_by && userId != null && userId === change.pm_signed_by;

  const transition = useMutation({
    mutationFn: (vars: {
      to: string; cancellation_reason?: string;
      rejection_reason?: string; reopen_reason?: string;
    }) =>
      changesApi.transition(changeId, vars.to, vars),
    onSuccess: () => {
      setBlocked(null);
      qc.invalidateQueries({ queryKey: ['change', changeId] });
    },
    onError: (e: unknown, vars) => {
      const detail = errDetail(e) ?? 'Transition failed';
      // The memo-dialog transitions report inline; only the ordinary forward
      // moves offer the deviation banner.
      const viaDialog = vars.cancellation_reason || vars.rejection_reason || vars.reopen_reason;
      if (!viaDialog) setBlocked({ to: vars.to, reason: detail });
      else toast.error(detail);
    },
  });
  const signOff = useMutation({
    mutationFn: (role: 'pm' | 'quality') => changesApi.signOff(changeId, role),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['change', changeId] }),
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Sign-off failed'),
  });
  const customer = useMutation({
    mutationFn: (vars: { response: string; release_due_date?: string; release_due_reason?: string | null }) =>
      changesApi.customerResponse(changeId, vars.response,
        vars.response === 'accepted'
          ? { release_due_date: vars.release_due_date, release_due_reason: vars.release_due_reason }
          : undefined),
    onSuccess: () => {
      setAcceptOpen(false);
      qc.invalidateQueries({ queryKey: ['change', changeId] });
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Failed to record customer response'),
  });
  const internalApprove = useMutation({
    mutationFn: (vars: { note?: string | null; release_due_date: string }) =>
      changesApi.approveInternalCosts(changeId, {
        note: vars.note ?? null,
        release_due_date: vars.release_due_date,
        release_due_reason: null,
      }),
    onSuccess: () => {
      toast.success(t('internal.approved'))
      setInternalOpen(false);
      qc.invalidateQueries({ queryKey: ['change', changeId] })
    },
    onError: (e: unknown) => toast.error(errDetail(e) ?? 'Approval failed'),
  });
  if (isLoading || !change) return <div className="p-6 text-slate-400">Loading…</div>;

  // A deep link into a tab the viewer or the phase does not allow — a
  // governance tab without authz, or any later-phase tab while capturing —
  // falls back to overview rather than rendering a blank/forbidden tab.
  const effectiveTab: Tab =
    (GOVERNANCE_TABS.includes(tab) && !canSeeGovernance) || isTabLocked(change.status, tab)
      ? 'overview' : tab;

  const advance = (to: string) => {
    if (to === 'cancelled') { setCancelOpen(true); return; }
    if (to === 'rejected') { setRejectOpen(true); return; }
    // Leaving a rejected change is a reopen, wherever the button lives.
    if (change.status === 'rejected') { setReopenOpen(true); return; }
    transition.mutate({ to });
  };

  return (
    <div className="max-w-5xl mx-auto p-6">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold flex items-center gap-3">
          <span>
            <span className="font-mono text-slate-400">{change.change_number}</span> — {change.title}
            {/* Which project this belongs to, one line under the name. */}
            {projectLabel(change.project_number, change.project_name) && (
              <Link data-testid="change-project"
                to={`/projects/${change.project_id}`}
                className="block text-sm font-normal text-slate-400 hover:text-sky-300">
                {projectLabel(change.project_number, change.project_name)}
              </Link>
            )}
          </span>
          {impl?.ready_to_go && (
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-green-900 text-green-100">
              ✓ {t('impl.readyToGo')}
            </span>
          )}
        </h1>
        <div className="flex gap-2">
          {change.status === 'rejected' && (
            <button className="px-3 py-1.5 text-sm rounded-lg bg-amber-700 hover:bg-amber-600 text-white"
                    onClick={() => setReopenOpen(true)}>Reopen</button>
          )}
          {change.status === 'on_hold' && (
            <button className="px-3 py-1.5 text-sm border border-slate-600 rounded-lg text-slate-200 hover:bg-slate-700"
                    onClick={() => advance('in_assessment')}>Resume</button>
          )}
          <button className="px-3 py-1.5 text-sm border rounded-lg text-red-600"
                  onClick={() => advance('cancelled')}>Cancel</button>
        </div>
      </div>

      <LifecycleStepper status={change.status} customerRelevant={change.customer_relevant} />

      {change.status === 'rejected' && (
        <div role="alert" className="mt-3 rounded-lg border border-red-800/60 bg-red-950/40 px-4 py-3 text-sm">
          <p className="font-semibold text-red-200">This change was rejected — the flow is stopped.</p>
          {change.rejection_reason && (
            <p className="mt-1 text-red-100/80">{change.rejection_reason}</p>
          )}
          <p className="mt-1 text-xs text-red-200/60">
            Reopen it to put it back into scoping. Both the rejection and the reopen are audited.
          </p>
        </div>
      )}

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
        open={rejectOpen}
        title="Reject change"
        warning={'Rejecting stops this change here. Assessments and routing stay as they are '
          + 'and nothing downstream runs again. It can be reopened later, with a reason — '
          + 'but the rejection stays on the record either way.'}
        label="Why is this rejected? (required, audited)"
        submitLabel="Reject change"
        danger
        onSubmit={(reason) => { setRejectOpen(false); transition.mutate({ to: 'rejected', rejection_reason: reason }); }}
        onClose={() => setRejectOpen(false)}
      />
      <ReasonDialog
        open={reopenOpen}
        title="Reopen change"
        warning={'Reopening puts the change back into scoping. The earlier rejection stays '
          + 'in the audit trail.'}
        label="Why is this being reopened? (required, audited)"
        submitLabel="Reopen change"
        onSubmit={(reason) => { setReopenOpen(false); transition.mutate({ to: 'scoping', reopen_reason: reason }); }}
        onClose={() => setReopenOpen(false)}
      />
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
        {EVERYDAY_TABS.map((tb) => {
          const locked = isTabLocked(change.status, tb);
          const isActivePhase = !locked && STATUS_ACTIVE_TAB[change.status] === tb;
          // Scoping leaves two jobs on the impact tab — pick the impacted items,
          // then confirm the set. Both are done when the confirmation lands.
          const openWork = tb === 'impacted'
            && change.status === 'scoping' && !change.impact_confirmed_at;
          return (
            <button key={tb}
              disabled={locked}
              title={locked ? t(lockedTitleKey(tb))
                : openWork ? t('tab.openWork')
                : isActivePhase ? t('tab.activePhase') : undefined}
              className={`pb-2 flex items-center gap-1.5 ${
                locked ? 'text-slate-600 cursor-not-allowed'
                : effectiveTab === tb ? 'border-b-2 border-sky-400 text-sky-300 font-medium'
                : 'text-slate-400 hover:text-slate-200'}`}
              onClick={() => { if (!locked) setTab(tb); }}>
              {isActivePhase && (
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" aria-label={t('tab.activePhase')} />
              )}
              {openWork && (
                <span data-testid="tab-open-work"
                  className="w-1.5 h-1.5 rounded-full bg-lime-400 ring-1 ring-lime-300/50"
                  aria-label={t('tab.openWork')} />
              )}
              {tb === 'implementation' ? t('impl.title') : tb === 'scoping' ? t('scoping.title') : tb[0].toUpperCase() + tb.slice(1)}
            </button>
          );
        })}
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
          <p><span className="text-slate-400">Type:</span> {change.change_type}</p>
          <p className="flex items-center gap-2">
            <span className="text-slate-400">Priority:</span>
            <PriorityEditor change={change} canEdit={isAdmin || isChangeLead} />
          </p>
          <p><span className="text-slate-400">Status:</span> {STATUS_LABELS[change.status] ?? change.status}</p>
          <p><span className="text-slate-400">Reason:</span> {change.reason ?? '—'}</p>
          <DescriptionEditor change={change} canEdit={canEditDescription} />
          <CustomerRelevantEditor change={change} canEdit={isAdmin || isChangeLead} />

          <ChangeAttachments change={change} />
        </div>
      )}

      {effectiveTab === 'scoping' && change && (
        <ScopingPanel change={change}
          canSendRejection={!myActions ? true : isSalesMember} />
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
          {/* Assessment-phase concerns are department-scoped: an open one holds
              that department's own submit, not the whole change. */}
          <ConcernStrip changeId={changeId} editable={change.status === 'in_assessment'}
            scoped departments={departments}
            myDepartmentIds={myActions?.memberships ?? []} />
          <AssessmentRouting changeId={changeId} />
          <ul className="text-sm divide-y border rounded-lg">
          {change.assessments.map((a) => (
            <li key={a.id} className="px-4 py-2">
              <div className="flex justify-between items-center gap-3">
                <span className="flex items-center gap-1.5">
                  {deptName(a.department_id)}
                  {change.blocked_department_ids?.includes(a.department_id) && (
                    <span data-testid="dept-on-hold" title={t('concern.title')}
                      className="inline-flex items-center rounded bg-amber-900/70 text-amber-200 px-1 py-0 text-[10px] leading-tight font-medium">
                      {t('concern.onHold')}
                    </span>
                  )}
                </span>
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
          {change.assessments.length === 0 && <li className="px-4 py-3 text-slate-400">No assessments.</li>}
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
              <QuotedPriceEditor change={change} canEdit={canEditQuotedPrice} />
              <p><span className="text-slate-400">Customer response:</span> {change.customer_response}</p>
              <div className="flex flex-wrap items-center gap-2">
                <button className="px-3 py-1.5 border rounded-lg"
                  onClick={() => setAcceptOpen((o) => !o)}>Customer accepted</button>
                <button className="px-3 py-1.5 border rounded-lg"
                  onClick={() => customer.mutate({ response: 'declined' })}>Customer declined</button>
              </div>
              {acceptOpen && (
                <div className="flex flex-wrap items-center gap-2 mt-2">
                  <label className="text-xs text-slate-400">{t('customer.releaseDue')}</label>
                  <input type="date" data-testid="accept-release-due" value={acceptDue}
                    onChange={(e) => setAcceptDue(e.target.value)}
                    className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
                  <input type="text" placeholder={t('customer.releaseDueReason')} value={acceptReason}
                    onChange={(e) => setAcceptReason(e.target.value)}
                    className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100 w-40" />
                  <button data-testid="accept-confirm"
                    className="bg-sky-600 hover:bg-sky-500 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
                    disabled={!acceptDue || customer.isPending}
                    onClick={() => customer.mutate({
                      response: 'accepted',
                      release_due_date: `${acceptDue}T23:59:59Z`,
                      release_due_reason: acceptReason || null,
                    })}>
                    {t('customer.confirmAccept')}
                  </button>
                </div>
              )}
              <div className="flex gap-2 pt-2">
                {canSignPm && (
                  <button className="px-3 py-1.5 border rounded-lg disabled:opacity-50"
                    disabled={!!change.pm_signed_by || samePersonBlocksPm}
                    onClick={() => signOff.mutate('pm')}>
                    PM sign-off {change.pm_signed_by ? '✓' : ''}
                  </button>
                )}
                {canSignQuality && (
                  <button className="px-3 py-1.5 border rounded-lg disabled:opacity-50"
                    disabled={!!change.quality_signed_by || samePersonBlocksQuality}
                    onClick={() => signOff.mutate('quality')}>
                    Quality sign-off {change.quality_signed_by ? '✓' : ''}
                  </button>
                )}
              </div>
              {(samePersonBlocksPm || samePersonBlocksQuality) && (
                <p className="text-xs text-amber-300">PM and Quality sign-off must be different users</p>
              )}
              <p className="text-xs text-slate-400">Approve requires customer acceptance + both sign-offs.</p>
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
              ) : canApproveInternalCosts ? (
                <>
                  <button
                    className="bg-emerald-700 hover:bg-emerald-600 text-white font-semibold px-4 py-2 rounded-lg text-sm disabled:opacity-50"
                    disabled={change.status !== 'costing' || internalApprove.isPending}
                    onClick={() => setInternalOpen((o) => !o)}>
                    {t('internal.approve')}
                  </button>
                  {internalOpen && (
                    <div className="flex flex-wrap items-center gap-2 mt-2">
                      <label className="text-xs text-slate-400">{t('customer.releaseDue')}</label>
                      <input type="date" data-testid="internal-release-due" value={internalDue}
                        onChange={(e) => setInternalDue(e.target.value)}
                        className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-100" />
                      <button data-testid="internal-approve-confirm"
                        className="bg-emerald-700 hover:bg-emerald-600 text-white px-2.5 py-1 rounded text-xs disabled:opacity-50"
                        disabled={!internalDue || internalApprove.isPending}
                        onClick={() => internalApprove.mutate({ release_due_date: `${internalDue}T23:59:59Z` })}>
                        {t('internal.approve')}
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-xs text-slate-400">
                  Only a Project Manager department member or an admin may approve internal costs.
                </p>
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
