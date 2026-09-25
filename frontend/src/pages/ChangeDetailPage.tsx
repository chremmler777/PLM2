import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client from '../api/client';
import { changesApi } from '../api/changes';
import { plantsApi } from '../api/plants';
import { planApi } from '../api/changePlan';
import AssessmentBuckets from '../components/changes/AssessmentBuckets';
import { resolveWaitStates } from '../lib/waitStates';
import D1MasterPanel from '../components/changes/D1MasterPanel';
import SummationView from '../components/changes/SummationView';
import CostingBuckets from '../components/changes/CostingBuckets';
import QuoteBasis from '../components/changes/QuoteBasis';
import DeviationBanner from '../components/changes/DeviationBanner';
import ReasonDialog from '../components/changes/ReasonDialog';
import ImpactTree from '../components/changes/ImpactTree';
import OfferTab from '../components/changes/offer/OfferTab';
import ReleaseTab from '../components/changes/release/ReleaseTab';
import TimingTab from '../components/changes/timing/TimingTab';
import LifecycleStepper from '../components/changes/LifecycleStepper';
import CockpitSummary from '../components/changes/CockpitSummary';
import TransitionConfirmDialog, { type TransitionConfirm } from '../components/changes/TransitionConfirmDialog';
import { changeReleaseApi } from '../api/changeRelease';
import { validationIssuesApi, validationIssuesKey } from '../api/validationIssues';
import { releaseKey } from '../components/changes/release/releaseKeys';
import PnlCard from '../components/changes/PnlCard';
import ScopingPanel from '../components/changes/ScopingPanel';
import ChangeAttachments from '../components/changes/ChangeAttachments';
import CustomerMailLog from '../components/changes/CustomerMailLog';
import { PriorityEditor } from '../components/changes/PriorityEditor';
import AuditTimeline from '../components/changes/AuditTimeline';
import { CustomerRelevantEditor } from '../components/changes/CustomerRelevantEditor';
import { DescriptionEditor } from '../components/changes/DescriptionEditor';
import { ScopingMappingHint } from '../components/changes/ScopingMappingHint';
import { useDepartments } from '../hooks/queries/useWorkflows';
import { useAuth } from '../contexts/AuthContext';
import { t } from '../i18n/cmLabels';
import {
  STATUS_LABELS, OFF_PATH_STATUSES, EVERYDAY_TABS, GOVERNANCE_TABS, TAB_UNLOCK_STATUS, STATUS_ACTIVE_TAB,
  activeTabsFor, resolveChangeTab, changeTabLabel, type ChangeTab,
  decodeLogValue,
} from '../lib/changeStatus';
import { getActsAsDepartmentId } from '../lib/actsAs';
import { projectLabel } from '../lib/project';
import { CHANGE_STATUS_ORDER, type ChangeStatus } from '../types/change';

const errDetail = (e: unknown): string | undefined =>
  (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail

type Tab = ChangeTab;
// F2: before costing there's no cost basis yet: the costing tab is locked and
// PnlCard hides itself for the same statuses.
const BEFORE_COSTING: string[] = ['captured', 'scoping', 'in_assessment'];
// Statuses from which a change can still be cancelled (mirrors the backend's
// allowed transitions): released only closes, closed/cancelled/rejected are done.
const CANCELLABLE: string[] = [
  'captured', 'scoping', 'in_assessment', 'costing', 'quoting', 'quoted',
  'approved', 'in_implementation', 'in_validation', 'on_hold',
];
/** Where a change opens without ?tab: the tab its current phase is worked on. */
const defaultTabFor = (status: string): Tab =>
  STATUS_ACTIVE_TAB[status as ChangeStatus] ?? (status === 'closed' ? 'release' : 'overview');
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
  // Always explicit: without ?tab the page opens on the phase's tab.
  const setTab = (t: Tab) => setSearchParams({ tab: t }, { replace: true });
  const [blocked, setBlocked] = useState<{ to: string; reason: string } | null>(null);
  // Bumped on every reported block, even an identical one, so the banner's
  // scroll-into-view effect re-fires on a second, otherwise-unchanged block.
  const [blockedSeq, setBlockedSeq] = useState(0);
  const [cancelOpen, setCancelOpen] = useState(false);
  // Rejecting and reopening both stop or restart the flow, so both go through
  // a memo dialog rather than a bare button.
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reopenOpen, setReopenOpen] = useState(false);
  // Pulling a change from quote creation back into costing: same people who
  // may close costing (PM, Sales, lead, admin), always with a reason.
  const [reopenCostingOpen, setReopenCostingOpen] = useState(false);
  // F4: the last look before a step that cannot simply be undone.
  const [confirmTo, setConfirmTo] = useState<string | null>(null);

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
  // An expired session answers this query with an error object, not an
  // array — that must degrade to "no plant default", not a black page.
  const projectPlantId = (Array.isArray(projects) ? projects : [])
    .find((p) => p.id === change?.project_id)?.plant_id ?? null;
  const { data: impl } = useQuery({
    queryKey: ['change', changeId, 'implementation'],
    queryFn: () => changesApi.getImplementation(changeId),
    enabled: !!change && ['in_implementation', 'in_validation', 'released'].includes(change.status),
  });
  // Stage 8: the per-department board and its escalations. The tracking card
  // asks for the same keys, so the banner costs no extra request; both are
  // needed here because the waits are derived from them.
  const implTracked = !!change && change.status === 'in_implementation';
  const { data: implState = [] } = useQuery({
    queryKey: ['change', changeId, 'impl-state'],
    queryFn: () => changesApi.implementationState(changeId),
    enabled: implTracked,
  });
  const { data: implEscalations = [] } = useQuery({
    queryKey: ['change', changeId, 'impl-escalations'],
    queryFn: () => changesApi.listImplEscalations(changeId),
    enabled: implTracked,
  });
  // Stage 9: the validation board. Shares the panel's cache key, so the banner
  // costs no extra request; the waits below are derived from it.
  const { data: validation } = useQuery({
    queryKey: ['change', changeId, 'validation'],
    queryFn: () => changesApi.validationState(changeId),
    enabled: !!change && change.status === 'in_validation',
  });
  // At approved the timing waits on team confirmation; same cache key as the
  // Timing tab's feedback panel, so it costs no extra request there.
  const { data: planFeedback } = useQuery({
    queryKey: ['change', changeId, 'plan-feedback'],
    queryFn: () => planApi.feedback(changeId),
    enabled: !!change && change.status === 'approved',
  });
  // After the baseline, open plan deviations are named in "Blocked by"; same
  // key as the Timing tab's panel.
  const tracking = !!change && ['approved', 'in_implementation', 'in_validation'].includes(change.status);
  const { data: planDeviations = [] } = useQuery({
    queryKey: ['change', changeId, 'plan-deviations'],
    queryFn: () => planApi.deviations(changeId),
    enabled: tracking && !!change?.timing_validated_at,
  });
  const openPlanDeviations = planDeviations.filter((d) => d.status === 'open').length;
  // Open validation issues hold the release and name their escalation level.
  const { data: validationIssues = [] } = useQuery({
    queryKey: validationIssuesKey(changeId),
    queryFn: () => validationIssuesApi.list(changeId),
    enabled: !!change && ['in_validation', 'in_implementation'].includes(change.status),
  });
  // The release guard's reasons (same key as the Release tab).
  const { data: releaseState } = useQuery({
    queryKey: releaseKey(changeId),
    queryFn: () => changeReleaseApi.get(changeId),
    enabled: !!change && change.status === 'in_validation',
  });
  // The detailed plan's progress, for the "end implementation" confirmation.
  const { data: detailedPlan, isLoading: detailedPlanLoading } = useQuery({
    queryKey: ['change', changeId, 'plan', 'detailed'],
    queryFn: () => planApi.get(changeId, 'detailed'),
    enabled: confirmTo === 'in_validation',
  });
  const { data: gates = [] } = useQuery({
    queryKey: ['change', changeId, 'gates'],
    queryFn: () => changesApi.getGates(changeId),
  });
  const { data: deviations = [] } = useQuery({
    queryKey: ['change', changeId, 'deviations'],
    queryFn: () => changesApi.listDeviations(changeId),
  });
  // The waits are derived from data the page already shows; this shares the
  // concern cache key with the strips, so it costs no extra request.
  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => changesApi.listConcerns(changeId),
  });
  const { data: myActions } = useQuery({
    queryKey: ['change-my-actions', changeId],
    queryFn: () => changesApi.myActions(changeId),
  });
  // Resume (on_hold): the status held before the hold, read off the
  // changelog's status entries rather than assumed — a change can be held
  // from any status, not only in_assessment.
  const { data: changelog } = useQuery({
    queryKey: ['change', changeId, 'changelog'],
    queryFn: () => changesApi.changelog(changeId),
    enabled: !!change && change.status === 'on_hold',
  });
  const resumeTo = (() => {
    const holdEntries = (changelog ?? []).filter(
      (e) => e.field_name === 'status' && decodeLogValue(e.new_value) === 'on_hold');
    const lastHold = holdEntries[holdEntries.length - 1];
    return decodeLogValue(lastHold?.old_value) || 'in_assessment';
  })();
  const { data: departments = [] } = useDepartments();
  const { isAdmin: isRealAdmin, userId } = useAuth();
  // The whole point of acts-as is walking the flow through a department's
  // eyes: the backend already drops the admin bypass then (spec D2), so the
  // page must drop every personal privilege too — admin AND change-lead.
  // Otherwise "act as APQP" on a change you happen to lead still shows the
  // full board, and nothing looks different from admin.
  const actingAs = getActsAsDepartmentId() != null;
  const isAdmin = isRealAdmin && !actingAs;
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
  const schedulingDeptId = departments.find((d) => d.name === 'Scheduling')?.id;
  const isChangeLead = !actingAs
    && userId != null && change?.lead_id != null && userId === change.lead_id;
  const isQualityMember = !!myActions && qualityDeptId !== undefined
    && myActions.memberships.includes(qualityDeptId);
  const isPmMember = !!myActions && pmDeptId !== undefined
    && myActions.memberships.includes(pmDeptId);
  const isSalesMember = !!myActions && salesDeptId !== undefined
    && myActions.memberships.includes(salesDeptId);
  const isSchedulingMember = !!myActions && schedulingDeptId !== undefined
    && myActions.memberships.includes(schedulingDeptId);
  const isGovernanceDept = isQualityMember || isPmMember;
  const canSeeGovernance = isAdmin || isChangeLead || isGovernanceDept;
  // Governance authz (mirrors the backend 403 gates in change_service.py):
  // sign-off is department-gated with no lead bypass; quoted price and
  // internal-cost approval keep the lead/PM exceptions the backend allows.
  const canSignPm = isAdmin || isPmMember;
  const canSignQuality = isAdmin || isQualityMember;
  const canApproveInternalCosts = isAdmin || isPmMember;
  const canEditQuotedPrice = isAdmin || isChangeLead || isSalesMember;
  // The whole cost picture is PM/Sales/lead/admin business; a department sees
  // its own bucket and nobody else's figures.
  const canSeeCosts = isAdmin || isChangeLead || isSalesMember || isPmMember;
  // The description is written during capture, and capture is Sales' job — the
  // backend PATCH gate allows lead / Sales / admin, so the editor must too.
  const canEditDescription = isAdmin || isChangeLead || isSalesMember;
  // Sales (plus lead/admin) publishes the plan and acknowledges the weight delta.
  const canPublishPlan = isAdmin || isChangeLead || isSalesMember;
  // Timing (spec 2026-09-25): plan editors and who publishes to the customer.
  const canEditPlan = isAdmin || isChangeLead || isSalesMember || isPmMember || isSchedulingMember;
  const canPublishTiming = isAdmin || isChangeLead || isSalesMember;
  // How the change reaches the line (bank build mode): the backend allows
  // Scheduling, PM, the change lead and admin, not Sales.
  const canSetBankBuild = isAdmin || isChangeLead || isSchedulingMember || isPmMember;
  // Deviation lock / escalate: PM, Sales, lead, admin (spec section 3).
  const canDecideDeviation = isAdmin || isChangeLead || isPmMember || isSalesMember;
  // Release checklist rows beyond the owner department, and the lessons step.
  const canManageRelease = isAdmin || isChangeLead || isPmMember;

  const transition = useMutation({
    mutationFn: (vars: {
      to: string; cancellation_reason?: string;
      rejection_reason?: string; reopen_reason?: string; reason?: string;
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
      const viaDialog = vars.cancellation_reason || vars.rejection_reason || vars.reopen_reason || vars.reason;
      if (!viaDialog) { setBlocked({ to: vars.to, reason: detail }); setBlockedSeq((n) => n + 1); }
      else toast.error(detail);
    },
  });
  if (isLoading || !change) return <div className="p-6 text-slate-400">Loading…</div>;

  // No ?tab, or one that doesn't resolve (old names like ?tab=commercial,
  // ?tab=implementation, or anything unknown), opens on the tab the change's
  // current phase is worked on — not always "overview" any more. A deep link
  // into a tab the viewer or the phase does not allow — a governance tab
  // without authz, or any later-phase tab while capturing — still falls back
  // to overview rather than rendering a blank/forbidden tab (below).
  const tab: Tab = resolveChangeTab(rawTab, change.status) ?? defaultTabFor(change.status);
  const effectiveTab: Tab =
    (GOVERNANCE_TABS.includes(tab) && !canSeeGovernance) || isTabLocked(change.status, tab)
      ? 'overview' : tab;
  // Actions and waits may still name old tabs; resolve them the same way.
  const goTab = (raw: string) => setTab(resolveChangeTab(raw, change.status) ?? 'overview');

  const advance = (to: string) => {
    if (to === 'cancelled') { setCancelOpen(true); return; }
    if (to === 'rejected') { setRejectOpen(true); return; }
    // Leaving a rejected change is a reopen, wherever the button lives.
    if (change.status === 'rejected') { setReopenOpen(true); return; }
    // Closing costing, ending implementation, releasing and closing are asked once more.
    if ((change.status === 'costing' && to === 'quoting')
      || ['in_validation', 'released', 'closed'].includes(to)) { setConfirmTo(to); return; }
    transition.mutate({ to });
  };

  // F10: who may take which next step, mirroring the backend's 403 gates.
  const needs = (step: string): string | null => {
    switch (step) {
      case 'to:quoting': return isAdmin || isChangeLead || isSalesMember || isPmMember ? null
        : 'Needs Sales, the Project Manager or the change lead';
      case 'offer':
      case 'answer': return canEditQuotedPrice ? null : 'Needs Sales or the change lead';
      // Only the missing side gates the step: a viewer who can sign PM but
      // not Quality is still let through once PM is the only side left open.
      case 'signoff': return ((!change.pm_signed_by && canSignPm) || (!change.quality_signed_by && canSignQuality))
        ? null : 'Needs the Project Manager and Quality';
      case 'internal-approval': return canApproveInternalCosts ? null : 'Needs the Project Manager';
      case 'validate-timing': return canEditPlan || canPublishTiming ? null
        : 'Needs the Project Manager, Scheduling or Sales';
      case 'to:released':
      case 'to:closed': return canManageRelease ? null : 'Needs the Project Manager or the change lead';
      default: return null;
    }
  };

  const confirm: TransitionConfirm | null = (() => {
    if (!confirmTo) return null;
    if (confirmTo === 'quoting') {
      return {
        to: confirmTo, title: 'Close costing',
        consequence: 'Closing costing freezes every department\'s numbers and hands the change to Sales for the offer. '
          + 'Reopening costing later needs a reason and is recorded.',
        open: (change.costing_pending_department_ids ?? []).map((d) => `${deptName(d)}: cost input not entered`),
        allClear: 'Every department has entered its cost input.',
        confirmLabel: 'Close costing',
      };
    }
    if (confirmTo === 'in_validation') {
      const tasks = (detailedPlan?.tasks ?? []).filter((x) => !x.is_idea && !x.is_summary);
      const notDone = tasks.filter((x) => (x.progress_pct ?? 0) < 100 && !x.actual_finish);
      const avg = tasks.length ? Math.round(tasks.reduce((a, x) => a + (x.actual_finish ? 100 : x.progress_pct ?? 0), 0) / tasks.length) : 0;
      const implRows = Array.isArray(implState) ? implState : implState.departments ?? [];
      const owing = implRows.filter((r) => r.owes_report).map((r) => deptName(r.department_id));
      return {
        to: confirmTo, title: 'End implementation',
        consequence: 'Implementation ends and the departments start validating. Sending the change back to '
          + 'implementation later needs a reason and is recorded.',
        open: [
          ...(notDone.length ? [`${notDone.length} of ${tasks.length} task${tasks.length === 1 ? '' : 's'} not finished (plan ${avg}% done)`] : []),
          ...(owing.length ? [`Progress report due: ${owing.join(', ')}`] : []),
          ...(openPlanDeviations ? [`${openPlanDeviations} plan deviation${openPlanDeviations === 1 ? '' : 's'} open`] : []),
        ],
        allClear: 'Every task is finished and reported.',
        confirmLabel: 'Move to validation',
        loading: detailedPlanLoading,
      };
    }
    if (confirmTo === 'released') {
      return {
        to: confirmTo, title: 'Release the change',
        consequence: 'Releasing puts the change live. It cannot be moved back; after release it can only be closed.',
        open: releaseState?.blockers ?? [],
        allClear: 'Validation, checklist and lessons are done.',
        confirmLabel: 'Release change',
        final: true,
        loading: !releaseState,
      };
    }
    return {
      to: confirmTo, title: 'Close the change',
      consequence: 'Closing is final. The change and its records become read only.',
      open: [], confirmLabel: 'Close change', final: true,
    };
  })();

  return (
    // One width for every tab, so switching tabs never moves the header.
    <div className="max-w-[1400px] mx-auto p-6">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold flex items-center gap-3">
          <span>
            <span className="font-mono text-slate-400">{change.change_number}</span> · {change.title}
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
                    onClick={() => advance(resumeTo)}>Resume</button>
          )}
          {CANCELLABLE.includes(change.status) && (
            <button className="px-3 py-1.5 text-sm border rounded-lg text-red-600"
                    onClick={() => advance('cancelled')}>Cancel</button>
          )}
        </div>
      </div>

      <LifecycleStepper status={change.status} customerRelevant={change.customer_relevant} />

      {change.status === 'rejected' && (
        <div role="alert" className="mt-3 rounded-lg border border-red-800/60 bg-red-950/40 px-4 py-3 text-sm">
          <p className="font-semibold text-red-200">This change was rejected, the flow is stopped.</p>
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
          seq={blockedSeq}
          onRetry={() => transition.mutate({ to: blocked.to })}
          onClose={() => setBlocked(null)}
        />
      )}
      <ReasonDialog
        open={rejectOpen}
        title="Reject change"
        warning={'Rejecting stops this change here. Assessments and routing stay as they are '
          + 'and nothing downstream runs again. It can be reopened later, with a reason, '
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
        open={reopenCostingOpen}
        title={t('costing.reopenTitle')}
        warning={t('costing.reopenWarning')}
        label={t('costing.reopenLabel')}
        submitLabel={t('costing.reopen')}
        onSubmit={(reason) => { setReopenCostingOpen(false); transition.mutate({ to: 'costing', reason }); }}
        onClose={() => setReopenCostingOpen(false)}
      />
      <TransitionConfirmDialog confirm={confirm} busy={transition.isPending}
        onClose={() => setConfirmTo(null)}
        onConfirm={() => { const to = confirmTo!; setConfirmTo(null); transition.mutate({ to }); }} />
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
        onAction={goTab}
        canSeeGovernance={canSeeGovernance}
        // What the change is waiting on — same list for every viewer, whoever
        // owns the next move.
        waits={resolveWaitStates(change, concerns, deptName, change.assessments,
          { state: implState, escalations: implEscalations }, validation,
          change.status === 'approved' ? planFeedback : null,
          { openPlanDeviations, releaseBlockers: releaseState?.blockers ?? null, validationIssues })}
        onGo={goTab}
        needs={needs}
      />

      <div className="border-b border-slate-700 flex items-center gap-4 text-sm mb-4">
        {EVERYDAY_TABS.map((tb) => {
          const locked = isTabLocked(change.status, tb);
          const isActivePhase = !locked && activeTabsFor(change.status, change.customer_relevant).includes(tb);
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
              {changeTabLabel(tb, change.customer_relevant, change.status)}
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
                {changeTabLabel(tb)}
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
          <p><span className="text-slate-400">Reason:</span> {change.reason ?? '-'}</p>
          <DescriptionEditor change={change} canEdit={canEditDescription} />
          <CustomerRelevantEditor change={change} canEdit={isAdmin || isChangeLead} />

          {/* Customer correspondence sits above the document lists: it is what
              everyone comes looking for, and it belongs to no phase. */}
          <div className="pt-3">
            <CustomerMailLog changeId={change.id} attachments={change.attachments ?? []} />
          </div>

          <ChangeAttachments change={change} />
        </div>
      )}

      {effectiveTab === 'scoping' && change && (
        <ScopingPanel change={change}
          canSendRejection={!myActions ? true : isSalesMember}
          canAnswerConcerns={isSalesMember} isPm={isPmMember} />
      )}

      {effectiveTab === 'impacted' && change && (
        <ImpactTree changeId={change.id} status={change.status}
          impactConfirmedByName={change.impact_confirmed_by_name}
          impactConfirmedAt={change.impact_confirmed_at}
          canConfirm={canConfirmImpact} />
      )}

      {effectiveTab === 'timing' && change && (
        <TimingTab change={change} departments={departments}
          myDepartmentIds={myActions?.memberships ?? []}
          canEditPlan={canEditPlan} canPublish={canPublishTiming} canSeeAll={canSeeCosts}
          canSetBankBuild={canSetBankBuild} canDecideDeviation={canDecideDeviation} isAdmin={isAdmin} />
      )}

      {effectiveTab === 'release' && change && (
        <ReleaseTab change={change} departments={departments}
          myDepartmentIds={myActions?.memberships ?? []}
          canSeeAll={canSeeCosts} canAcknowledge={canPublishPlan}
          canManage={canManageRelease}
          viewerId={actingAs ? null : userId} isAdmin={isAdmin} isSales={isSalesMember}
          onAdvance={advance} advancing={transition.isPending} />
      )}

      {effectiveTab === 'assessments' && (
        <div className="space-y-4">
          <ScopingMappingHint changeId={changeId} assessments={change.assessments} departments={departments} />
          {/* One bucket per routed department: status board collapsed, that
              department's workplace expanded. Everything that used to be a
              separate routing list or loose submit form lives inside it. */}
          <AssessmentBuckets change={change} departments={departments}
            myDepartmentIds={myActions?.memberships ?? []}
            editable={change.status === 'in_assessment'} isPm={isPmMember}
            canSeeAll={canSeeCosts}
            canAddDepartment={isAdmin || isChangeLead || isPmMember}
            userId={userId ?? null} isChangeLead={isChangeLead} />
        </div>
      )}

      {effectiveTab === 'costing' && (
        <div className="space-y-3 text-sm">
          <div data-testid="costing-stage" className="rounded-xl border border-slate-700 bg-slate-800/60 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-100">{t('costing.stageTitle')}</h2>
            <p className="mt-0.5 text-xs text-slate-400">{t('costing.stageBody')}</p>
          </div>
          {/* Costing closed: departments read only; whoever may close it may
              reopen it, with a reason on the record. */}
          {change.status === 'quoting' && (
            <div data-testid="costing-closed"
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-700 bg-slate-800/50 px-3 py-2 text-xs text-slate-400">
              <span>{t('costing.closedHint')}</span>
              {(isAdmin || isChangeLead || isSalesMember || isPmMember) && (
                <button type="button" data-testid="costing-reopen"
                  className="border border-slate-600 text-slate-200 hover:bg-slate-700 px-2.5 py-1 rounded-lg text-xs"
                  disabled={transition.isPending}
                  onClick={() => setReopenCostingOpen(true)}>
                  {t('costing.reopen')}
                </button>
              )}
            </div>
          )}
          {/* The P&L reads /summation, which only the cost roles may: mounting
              it for anyone else fires a request that can only 403. */}
          {canSeeCosts && <PnlCard change={change} departments={departments} />}
          {/* Costing is department work first: each bucket holds its own lines
              and lead time; the whole picture lives in the summation below, for
              the people entitled to see it. */}
          {!BEFORE_COSTING.includes(change.status) && (
            <CostingBuckets change={change} departments={departments}
              myDepartmentIds={myActions?.memberships ?? []}
              plants={(change.affected_plant_ids && change.affected_plant_ids.length > 0
                ? allPlants.filter((p) => change.affected_plant_ids!.includes(p.id))
                : allPlants)
                .filter((p) => p.is_active !== false)
                .map((p) => ({ id: p.id, name: p.name, is_active: p.is_active }))}
              projectPlantId={projectPlantId}
              canSeeAll={canSeeCosts} editable={change.status === 'costing'}
              isPm={isPmMember || isAdmin} />
          )}
          {/* The whole picture, for the people who answer for it; at quoting
              also where Sales makes the binding vendor decisions. */}
          {!BEFORE_COSTING.includes(change.status) && canSeeCosts && (
            <SummationView changeId={changeId}
              status={change.status} canQuote={canEditQuotedPrice}
              plants={allPlants.map((p) => ({ id: p.id, name: p.name }))}
              validatedWeightG={change.validated_part_weight_g}
              deadline={change.active_deadline === 'release'
                ? { date: change.release_due_date, label: t('deadline.release') }
                : { date: change.required_by_date, label: t('deadline.quote') }} />
          )}
          {/* What the offer is judged against: production-time delta and the
              risks nobody could close. */}
          {!BEFORE_COSTING.includes(change.status) && canSeeCosts && change.customer_relevant && (
            <QuoteBasis changeId={changeId}
              plants={allPlants.map((p) => ({ id: p.id, name: p.name }))}
              concerns={concerns} departments={departments} />
          )}
        </div>
      )}

      {effectiveTab === 'offer' && (
        <OfferTab change={change}
          canWrite={canEditQuotedPrice} canSeePrices={canSeeCosts}
          canSignPm={canSignPm} canSignQuality={canSignQuality}
          canApproveInternalCosts={canApproveInternalCosts}
          userId={userId ?? null}
          costSummary={canSeeCosts ? <SummationView changeId={changeId}
                status={change.status} canQuote={canEditQuotedPrice}
                plants={allPlants.map((p) => ({ id: p.id, name: p.name }))}
                validatedWeightG={change.validated_part_weight_g}
                deadline={change.active_deadline === 'release'
                  ? { date: change.release_due_date, label: t('deadline.release') }
                  : { date: change.required_by_date, label: t('deadline.quote') }} /> : null} />
      )}

      {effectiveTab === 'd1' && (
        <D1MasterPanel changeId={changeId}
          canEditD1={isAdmin || isChangeLead || isQualityMember || isPmMember}
          canEditCustomerRelevant={isAdmin || isChangeLead} />
      )}

      {effectiveTab === 'audit' && (
        <AuditTimeline correlationId={change.change_number} />
      )}
    </div>
  );
}
