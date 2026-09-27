import { Link, useParams, useSearchParams } from 'react-router-dom';
import { useEffect, useId, useRef, useState } from 'react';
import { Check, Lock, MoreHorizontal } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { apiErrorMessage, toastError } from '../lib/apiError';
import client from '../api/client';
import { changesApi } from '../api/changes';
import { cockpitPart } from '../api/cockpitBundle';
import { plantsApi } from '../api/plants';
import { planApi } from '../api/changePlan';
import AssessmentBuckets from '../components/changes/AssessmentBuckets';
import { resolveWaitStates, earlyStageWaits, deriveAssessmentState, revisionsInCheckOf } from '../lib/waitStates';
import LeadPicker from '../components/changes/LeadPicker';
import { mayTransition, endStateOf, stoppedAtFrom } from '../lib/transitionRights';
import { plantText } from '../lib/plantName';
import { assessmentVerdictLabel, changeTypeLabel, verdictLabel, plural } from '../lib/humanLabels';
import D1MasterPanel from '../components/changes/D1MasterPanel';
import SummationView from '../components/changes/SummationView';
import CostingBuckets from '../components/changes/CostingBuckets';
import QuoteBasis from '../components/changes/QuoteBasis';
import DeviationBanner from '../components/changes/DeviationBanner';
import TransitionDeviationsPanel from '../components/changes/TransitionDeviationsPanel';
import ReasonDialog from '../components/changes/ReasonDialog';
import ImpactTree from '../components/changes/ImpactTree';
import OfferTab from '../components/changes/offer/OfferTab';
import ReleaseTab from '../components/changes/release/ReleaseTab';
import TimingTab from '../components/changes/timing/TimingTab';
import { groupDeviations } from '../components/changes/timing/DeviationsPanel';
import LifecycleStepper from '../components/changes/LifecycleStepper';
import CockpitSummary, { gateStateText } from '../components/changes/CockpitSummary';
import TransitionConfirmDialog, { type TransitionConfirm } from '../components/changes/TransitionConfirmDialog';
import { changeReleaseApi } from '../api/changeRelease';
import { validationIssuesApi, validationIssuesKey } from '../api/validationIssues';
import { releaseKey } from '../components/changes/release/releaseKeys';
import PnlCard from '../components/changes/PnlCard';
import IssuesPanel from '../components/changes/validation/IssuesPanel';
import { releaseOpenByIssues } from '../lib/issueTabs';
import ScopingPanel from '../components/changes/ScopingPanel';
import ChangeAttachments from '../components/changes/ChangeAttachments';
import MotherPlantTab from '../components/changes/motherPlant/MotherPlantTab';
import ReviewTab from '../components/changes/review/ReviewTab';
import { intakeKeys, intakesApi } from '../api/intakes';
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
  OFF_PATH_STATUSES, everydayTabsFor, transitionLabel, GOVERNANCE_TABS, TAB_UNLOCK_STATUS, STATUS_ACTIVE_TAB,
  activeTabsFor, resolveChangeTab, changeTabLabel, stoppedTabLocked, stoppedDefaultTab, type ChangeTab,
  decodeLogValue, STATUS_LABELS,
} from '../lib/changeStatus';
import { getActsAsDepartmentId } from '../lib/actsAs';
import { projectLabel } from '../lib/project';
import { unpricedByDepartment } from '../lib/unpriced';
import { CHANGE_STATUS_ORDER, type ChangeStatus, type GateKey } from '../types/change';
import { btnIcon, btnSm } from '../components/common/buttonStyles';
import { formatDate, formatMoney } from '../lib/format';

/** The change-detail queries refresh when the user comes back to the tab:
 *  other departments answer, approve and block while it sits in the
 *  background, and a stale cockpit invites 409s (the app default is off). */
const LIVE = { refetchOnWindowFocus: true } as const;

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
const defaultTabFor = (status: string, origin?: string | null): Tab =>
  // Mother plant (spec §14): scoping is informing the team, on its own tab.
  origin === 'mother_plant' && status === 'scoping' ? 'mother'
  // Engineering review (spec §17): the review is the work, and the record.
  : origin === 'engineering_review' ? 'review'
  : STATUS_ACTIVE_TAB[status as ChangeStatus] ?? (status === 'closed' ? 'release' : 'overview');
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
  // ?issue=<id> rides along when a link names a validation issue.
  const setTab = (t: Tab, issueId?: number) => setSearchParams(
    issueId != null ? { tab: t, issue: String(issueId) } : { tab: t }, { replace: true });
  const issueParam = Number(searchParams.get('issue'));
  const focusIssueId = Number.isInteger(issueParam) && issueParam > 0 ? issueParam : null;
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
  // Not feasible, and still going on: a transition deviation with a reason.
  const [overrideOpen, setOverrideOpen] = useState(false);
  // "Decide deviation #n": the Overview's decision panel scrolls to it once
  // (null: the panel itself; undefined: nothing to focus).
  const [focusDeviation, setFocusDeviation] = useState<number | null | undefined>(undefined);
  const tabsId = useId();
  const moreRef = useRef<HTMLDetailsElement>(null);

  const { data: change, isLoading } = useQuery({
    queryKey: ['change', changeId],
    queryFn: () => changesApi.get(changeId),
    ...LIVE,
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
    ...LIVE,
  });
  // Stage 8: the per-department board and its escalations. The tracking card
  // asks for the same keys, so the banner costs no extra request; both are
  // needed here because the waits are derived from them.
  const implTracked = !!change && change.status === 'in_implementation';
  const { data: implState = [] } = useQuery({
    queryKey: ['change', changeId, 'impl-state'],
    queryFn: () => changesApi.implementationState(changeId),
    enabled: implTracked,
    ...LIVE,
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
  // Counted by move (one edit and the rows it pushed), as the Timing tab's
  // panel groups them and the server counts them.
  const openPlanDeviations = groupDeviations(planDeviations)
    .filter((g) => [g.root, ...g.pushed].some((d) => d.status === 'open')).length;
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
    queryFn: () => cockpitPart(changeId, 'gates'),
    ...LIVE,
  });
  const { data: deviations = [] } = useQuery({
    queryKey: ['change', changeId, 'deviations'],
    queryFn: () => cockpitPart(changeId, 'deviations'),
    ...LIVE,
  });
  // The waits are derived from data the page already shows; this shares the
  // concern cache key with the strips, so it costs no extra request.
  const { data: concerns = [] } = useQuery({
    queryKey: ['change', changeId, 'concerns'],
    queryFn: () => cockpitPart(changeId, 'concerns'),
  });
  // Spec §17: a change from an intake may carry an engineering review (its
  // own track, or escalated: the answers stay as the scoping input).
  const { data: review } = useQuery({
    queryKey: intakeKeys.review(changeId),
    queryFn: () => intakesApi.review(changeId),
    enabled: !!change && (change.origin === 'engineering_review' || !!change.from_intake),
  });
  const hasReview = !!review && (review.is_review || review.answers.length > 0);
  const { data: myActions } = useQuery({
    queryKey: ['change-my-actions', changeId],
    queryFn: () => cockpitPart(changeId, 'my_actions'),
    ...LIVE,
  });
  // Your actions follow the change: an act done on any tab (confirming the
  // impact, answering, deciding) updates the change, and the list must not
  // keep offering what was just done. The first load is not a change.
  const seenChange = useRef<string | null>(null);
  const changeStamp = change ? `${change.updated_at}|${change.status}|${change.impact_confirmed_at ?? ''}` : null;
  useEffect(() => {
    if (!changeStamp) return;
    if (seenChange.current !== null && seenChange.current !== changeStamp) {
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] });
    }
    seenChange.current = changeStamp;
  }, [changeStamp, changeId, qc]);
  // Spec §16: waits, transition rights, the assessment round and the end
  // state, as the backend judges them for this viewer. Under ['change', id]
  // so every change mutation refreshes it; an older backend without the
  // endpoint leaves it undefined and the page derives what it can.
  const { data: stage } = useQuery({
    queryKey: ['change', changeId, 'stage-state'],
    queryFn: () => cockpitPart(changeId, 'stage_state'),
    retry: false,
    ...LIVE,
  });
  // Resume (on_hold): the status held before the hold, read off the
  // changelog's status entries rather than assumed — a change can be held
  // from any status, not only in_assessment.
  const { data: changelog } = useQuery({
    queryKey: ['change', changeId, 'changelog'],
    queryFn: () => changesApi.changelog(changeId),
    // Closed: the read-only banner names the day it closed.
    enabled: !!change && (change.status === 'on_hold' || change.status === 'closed'
      || (['rejected', 'cancelled'].includes(change.status) && !change.stopped_at)),
  });
  const resumeTo = (() => {
    const holdEntries = (changelog ?? []).filter(
      (e) => e.field_name === 'status' && decodeLogValue(e.new_value) === 'on_hold');
    const lastHold = holdEntries[holdEntries.length - 1];
    return decodeLogValue(lastHold?.old_value) || 'in_assessment';
  })();
  const { data: allDepartments = [] } = useDepartments();
  // Retired departments stay out of every picker below; one this change
  // already routed to keeps its name.
  const routedIds = new Set((change?.assessments ?? []).map((a) => a.department_id));
  const departments = allDepartments.filter((d) => d.is_active !== false || routedIds.has(d.id));
  const { isAdmin: isRealAdmin, userId } = useAuth();
  // The whole point of acts-as is walking the flow through a department's
  // eyes: the backend already drops the admin bypass then (spec D2), so the
  // page must drop every personal privilege too — admin AND change-lead.
  // Otherwise "act as APQP" on a change you happen to lead still shows the
  // full board, and nothing looks different from admin.
  const actingAs = getActsAsDepartmentId() != null;
  const isAdmin = isRealAdmin && !actingAs;
  const pendingDeviations = deviations.filter((d) => d.status === 'pending').length;
  const deptName = (id: number) => allDepartments.find((d) => d.id === id)?.name ?? '#' + id;
  // Client-side mirror of the confirm-impact authz: Development members only —
  // no admin shortcut, because the backend dropped it too (an admin who needs to
  // confirm acts as Development). Defaults to true until departments/memberships
  // have loaded, so the button doesn't flash-disabled.
  const rdDeptId = departments.find((d) => d.name === 'Development')?.id;
  const isDevelopmentMember = !!myActions && rdDeptId !== undefined
    && myActions.memberships.includes(rdDeptId);
  const canConfirmImpact = !myActions ? true : isDevelopmentMember;
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
  // Project Management writes it where it captures (spec §14: a mother-plant
  // change the PM started) or while nobody leads the change yet, the
  // backend's "pm_capture" right.
  const canEditDescription = isAdmin || isChangeLead || isSalesMember
    || (isPmMember && (change?.origin === 'mother_plant'
      || (['captured', 'scoping'].includes(change?.status ?? '') && change?.lead_id == null)));
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
  // Mother plant (spec §14): informing the team, scoping -> approved and the
  // "Inform mother plant" stamp are the PM's (lead, admin).
  const motherPlant = change?.origin === 'mother_plant';
  const canRunMotherPlant = isAdmin || isChangeLead || isPmMember;
  // The scoping meeting and its decision: the backend's verdict (stage-state),
  // else lead, PM or admin (the backend answers anyone else 403).
  const canRecordMeeting = stage?.can_record_meeting ?? (isAdmin || isChangeLead || isPmMember);

  // Transition rights (spec §16 P1 4): the backend's verdict for this viewer,
  // else the client mirror. A step the viewer may not take is not shown.
  const may = (to: string): boolean => {
    if (stage?.can_transition) return stage.can_transition[to] === true;
    return !!change && mayTransition(change, to,
      { isAdmin, isChangeLead, isPm: isPmMember, isSales: isSalesMember });
  };
  const override = useMutation({
    mutationFn: (reason: string) => changesApi.proposeDeviation(changeId, { to_status: 'costing', reason }),
    onSuccess: () => {
      toast.success(t('next.overrideSent'));
      qc.invalidateQueries({ queryKey: ['change', changeId] });
    },
    onError: (e: unknown) => toastError(e, 'Could not propose the deviation'),
  });

  // Close costing names the hours nobody can price (no cost sheet rate): the
  // summation lists them. Cost roles only, like every figure.
  // Also read while costing runs: the "Close costing" step holds on the same
  // facts the Costing tab states (nothing costed, departments not costed yet).
  const { data: closingSummation, isLoading: closingSummationLoading } = useQuery({
    queryKey: ['change-summation', changeId],
    queryFn: () => changesApi.getSummation(changeId),
    enabled: (confirmTo === 'quoting' || change?.status === 'costing') && canSeeCosts,
  });
  // What is worth a second look before "Close costing", read like
  // CostingBuckets reads it: a total of zero with nothing waiting for a rate,
  // or departments with nothing booked. A warning only, never a hold: the
  // backend counts a zero line as an answer (costing_pending_department_ids),
  // so a change that legitimately costs nothing must still close.
  const costingWarning = (() => {
    const sum = closingSummation;
    if (!change || change.status !== 'costing' || !sum || !canSeeCosts) return null;
    const unpricedDepts = new Set((sum.unpriced_lines ?? []).map((l) => l.department_id));
    if (Math.abs(sum.totals?.grand_total ?? 0) < 0.005 && unpricedDepts.size === 0) {
      return `The total is ${formatMoney(0, sum.currency ?? 'EUR')}. Check that nothing was forgotten.`;
    }
    const deptIds = [...new Set(change.assessments.map((a) => a.department_id))];
    const unbooked = deptIds.filter((id) => {
      const row = sum.by_department.find((d) => d.department_id === id);
      const total = row ? row.one_time_internal + row.one_time_external
        + row.lifecycle_internal + row.lifecycle_external : 0;
      return total === 0 && !unpricedDepts.has(id);
    });
    if (unbooked.length === 0) return null;
    return `${unbooked.length} of ${deptIds.length} department${deptIds.length === 1 ? '' : 's'} `
      + `booked no cost: ${unbooked.map(deptName).join(', ')}. Check that nothing was forgotten.`;
  })();
  // Releasing past open guards asks for a deviation with the reason, here and
  // now, instead of a bare refusal and a second dialog.
  const askDeviation = useMutation({
    mutationFn: (v: { to: string; reason: string }) =>
      changesApi.proposeDeviation(changeId, { to_status: v.to, reason: v.reason }),
    onSuccess: (d) => {
      toast.success(`Deviation #${d.id} asked. Someone other than you approves it; then the step can be taken.`);
      qc.invalidateQueries({ queryKey: ['change', changeId] });
      qc.invalidateQueries({ queryKey: ['change-my-actions', changeId] });
    },
    onError: (e: unknown) => toastError(e, 'Could not ask for the deviation'),
  });

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
      const detail = apiErrorMessage(e, `Could not ${transitionLabel(vars.to, change?.status).toLowerCase()}`);
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
  // A rejected or cancelled change (also a rejection closed afterwards) ends
  // at the stage it stopped at: it opens on Overview (Scoping when the
  // meeting rejected it), no tab is the active phase, and the stages it never
  // reached stay locked. The rejection closure lives on Scoping, so a
  // rejected change always keeps it.
  const stopped = (() => {
    const kind = stage?.end_state?.kind ?? endStateOf(change);
    if (kind !== 'rejected' && kind !== 'cancelled') return null;
    const at = stage?.end_state?.stopped_at ?? stoppedAtFrom(change,
      (changelog ?? []).filter((e) => e.field_name === 'status')
        .map((e) => ({ old_value: decodeLogValue(e.old_value), new_value: decodeLogValue(e.new_value) })));
    return { kind, at };
  })();
  const tab: Tab = resolveChangeTab(rawTab, change.status, change.origin)
    ?? (stopped ? stoppedDefaultTab(stopped.kind, stopped.at) : defaultTabFor(change.status, change.origin));
  // Once a validation issue exists the Release tab stays open through a loop
  // back to implementation: the validation record never disappears.
  const stoppedLocked = (tb: Tab) => !!stopped && stoppedTabLocked(stopped.at, tb)
    && !(stopped.kind === 'rejected' && tb === 'scoping');
  const tabLocked = (tb: Tab) => stoppedLocked(tb) || (!stopped && isTabLocked(change.status, tb)
    && !(tb === 'release' && releaseOpenByIssues(change.status, validationIssues.length)));
  // The tabs the tablist renders. A tab not among them (?tab=review while the
  // review still loads, or a tab this change has no longer) falls back to
  // Overview, so one rendered tab is always selected and focusable.
  const everydayTabs = everydayTabsFor(change.origin, hasReview);
  const renderedTabs: Tab[] = canSeeGovernance ? [...everydayTabs, ...GOVERNANCE_TABS] : everydayTabs;
  const effectiveTab: Tab =
    !renderedTabs.includes(tab) || (GOVERNANCE_TABS.includes(tab) && !canSeeGovernance) || tabLocked(tab)
      ? 'overview' : tab;
  // Actions and waits may still name old tabs; resolve them the same way.
  const goTab = (raw: string, issueId?: number) =>
    setTab(resolveChangeTab(raw, change.status, change.origin) ?? 'overview', issueId);

  const advance = (to: string) => {
    if (to === 'cancelled') { setCancelOpen(true); return; }
    if (to === 'rejected') { setRejectOpen(true); return; }
    // Leaving a rejected change is a reopen, wherever the button lives.
    if (change.status === 'rejected') { setReopenOpen(true); return; }
    // Kicking off, closing the assessment and recalling it are asked once more.
    if ((change.status === 'captured' && to === 'scoping')
      || (change.status === 'in_assessment' && (to === 'costing' || to === 'scoping'))) {
      setConfirmTo(to); return;
    }
    // Closing costing, recording the approval, finishing implementation,
    // releasing and closing are asked once more.
    if ((change.status === 'costing' && to === 'quoting')
      || ((change.status === 'quoted' || change.status === 'costing') && to === 'approved' && !motherPlant)
      || (motherPlant && change.status === 'scoping' && to === 'approved')
      || ['in_validation', 'released', 'closed'].includes(to)) { setConfirmTo(to); return; }
    transition.mutate({ to });
  };

  // F10: who may take which next step, mirroring the backend's 403 gates.
  const needs = (step: string): string | null => {
    switch (step) {
      // Rights only: what the costing looks like is a warning (costingWarning),
      // never a hold the backend does not know.
      case 'to:quoting': return !(isAdmin || isChangeLead || isSalesMember || isPmMember)
        ? 'Needs Sales, the Project Manager or the change lead'
        : null;
      case 'offer':
      case 'answer': return canEditQuotedPrice ? null : 'Needs Sales or the change lead';
      // Only the missing side gates the step: a viewer who can sign PM but
      // not Quality is still let through once PM is the only side left open.
      case 'signoff': return ((!change.pm_signed_by && canSignPm) || (!change.quality_signed_by && canSignQuality))
        ? null : 'Needs the Project Manager and Quality';
      case 'internal-approval': return canApproveInternalCosts ? null : 'Needs the Project Manager';
      case 'validate-timing': {
        if (!(canEditPlan || canPublishTiming)) return 'Needs the Project Manager, Scheduling or Sales';
        // The Timing tab holds its "Validate timing" until every team has
        // confirmed: the cockpit does not offer a step the tab refuses.
        const waiting = (planFeedback?.required ?? []).filter((r) => !(r.verdict === 'confirmed' && !r.stale));
        if (planFeedback && !planFeedback.validated_at && (!planFeedback.all_confirmed || waiting.length > 0)) {
          return waiting.length > 0
            ? `Waiting for ${waiting.map((r) => r.department_name).join(', ')} to confirm the timing`
            : 'Waiting for every team to confirm the timing';
        }
        return null;
      }
      case 'info-send':
      case 'inform-mother': return canRunMotherPlant ? null : 'Needs the Project Manager or the change lead';
      // The backend's can_transition already judged the hop (rights and the
      // hard blockers); the client mirror only stands in without it.
      case 'to:approved': return stage?.can_transition || !motherPlant || canRunMotherPlant ? null
        : 'Needs the Project Manager or the change lead';
      case 'to:released':
      case 'to:closed': return canManageRelease ? null : 'Needs the Project Manager or the change lead';
      default: return null;
    }
  };

  const deptLabel = (d: { department_id: number; department_name?: string | null }) =>
    d.department_name ?? deptName(d.department_id);
  // The assessment round: stage-state's, else derived from the rows.
  const baseAssessment = change.status !== 'in_assessment' ? null
    : stage?.assessment ?? deriveAssessmentState(change.assessments, deptName, concerns);
  // A not-feasible answer overridden by a transition deviation to costing.
  const costingDeviation = deviations.find((d) => d.to_status === 'costing' && d.status === 'approved')
    ?? deviations.find((d) => d.to_status === 'costing' && d.status === 'pending');
  const assessmentState = baseAssessment && costingDeviation
    ? { ...baseAssessment, override: costingDeviation.status as 'pending' | 'approved' }
    : baseAssessment;
  const kickoffMissing = [
    ...(change.description?.trim() ? [] : [t('kickoff.description')]),
    ...((change.attachments?.length ?? 0) > 0 ? [] : [t('kickoff.attachment')]),
    ...(change.customer_relevant && !change.required_by_date ? [t('deadline.quote')] : []),
    ...(change.lead_id == null ? [t('cockpit.noLead')] : []),
  ];
  const confirm: TransitionConfirm | null = (() => {
    if (!confirmTo) return null;
    // Resuming from hold goes back to where the change stood: a plain resume,
    // never the forward step's confirm ("Finish implementation", "Release").
    if (change.status === 'on_hold' && confirmTo !== 'cancelled') {
      const verb = transitionLabel(confirmTo, 'on_hold');
      return { to: confirmTo, title: verb,
        consequence: `The change goes back to ${STATUS_LABELS[confirmTo as ChangeStatus] ?? confirmTo}, where it was put on hold. `
          + 'This step is recorded in the audit trail.',
        open: [], confirmLabel: verb };
    }
    if (change.status === 'captured' && confirmTo === 'scoping') {
      return {
        to: confirmTo, title: t('confirm.kickoffTitle'),
        consequence: t('confirm.kickoffBody'),
        open: kickoffMissing,
        allClear: t('kickoff.ready'),
        confirmLabel: t('confirm.kickoffGo'),
        // A change from the other plant has no deviation path at kickoff:
        // the hand-over waits until nothing is missing.
        holdWhileOpen: motherPlant,
      };
    }
    if (change.status === 'in_assessment' && confirmTo === 'scoping') {
      return {
        to: confirmTo, title: t('next.backToScoping'),
        consequence: t('confirm.recallBody'),
        open: [], confirmLabel: t('next.backToScoping'),
        // Throwing the round away is answered for: the reason is on the record.
        reason: { label: t('confirm.recallReason'), placeholder: t('confirm.recallReasonHint') },
      };
    }
    if (change.status === 'in_assessment' && confirmTo === 'costing') {
      const a = assessmentState;
      return {
        to: confirmTo, title: t('confirm.closeAssessmentTitle'),
        consequence: t('confirm.closeAssessmentBody'),
        open: (a?.waiting_on ?? []).map((d) => `${deptLabel(d)}: ${t('confirm.notAnswered')}`),
        allClear: t('confirm.allAnswered'),
        info: [
          ...(a?.verdicts ?? []).map((v) => {
            // "Not impacted" is stored as feasible: say what was answered.
            const row = change.assessments.find((x) => x.department_id === v.department_id
              && x.verdict === v.verdict && x.details?.impacted === false);
            return `${deptLabel(v)}: ${row ? assessmentVerdictLabel(row) : v.verdict_label ?? verdictLabel(v.verdict)}`
              + (v.open_risks ? `, ${plural(v.open_risks, 'open risk')}` : '');
          }),
          ...(a?.open_risks ?? []).map((r) => `${t('confirm.risk')} ${r.department_name ?? ''}: `
            + `${r.risk_type_label ?? r.risk_type ?? ''}${r.severity ? ` (${r.severity})` : ''}, ${r.note}`),
          ...(a?.override === 'approved' ? [t('confirm.overrideApproved')] : []),
        ],
        confirmLabel: t('next.closeAssessment'),
      };
    }
    if (confirmTo === 'quoting') {
      // Truthful: a department still owing its input, and hours that were
      // entered but have no rate (not counted, the total is too low).
      const unpriced = unpricedByDepartment(closingSummation?.unpriced_lines, deptName);
      return {
        to: confirmTo, title: transitionLabel('quoting'),
        consequence: 'Closing costing freezes every department\'s numbers and hands the change to Sales for the offer. '
          + 'Reopening costing later needs a reason and is recorded.',
        open: [
          ...(change.costing_pending_department_ids ?? []).map((d) => `${deptName(d)}: cost input not entered`),
          ...unpriced.map((u) => `${u.message}: the total is too low`),
        ],
        allClear: 'Every department has entered its cost input, and every line has a rate.',
        warning: costingWarning ?? undefined,
        confirmLabel: transitionLabel('quoting'),
        loading: canSeeCosts && closingSummationLoading,
      };
    }
    if (confirmTo === 'in_validation') {
      const tasks = (detailedPlan?.tasks ?? []).filter((x) => !x.is_idea && !x.is_summary);
      const notDone = tasks.filter((x) => (x.progress_pct ?? 0) < 100 && !x.actual_finish);
      const avg = tasks.length ? Math.round(tasks.reduce((a, x) => a + (x.actual_finish ? 100 : x.progress_pct ?? 0), 0) / tasks.length) : 0;
      const implRows = Array.isArray(implState) ? implState : implState.departments ?? [];
      const owing = implRows.filter((r) => r.owes_report).map((r) => deptName(r.department_id));
      return {
        to: confirmTo, title: transitionLabel('in_validation'),
        consequence: 'Implementation ends and the departments start validating. Sending the change back to '
          + 'implementation later needs a reason and is recorded.',
        open: [
          ...(notDone.length ? [`${notDone.length} of ${tasks.length} task${tasks.length === 1 ? '' : 's'} not finished (plan ${avg}% done)`] : []),
          ...(owing.length ? [`Progress report due: ${owing.join(', ')}`] : []),
          ...(openPlanDeviations ? [`${openPlanDeviations} move${openPlanDeviations === 1 ? '' : 's'} with plan deviations open`] : []),
        ],
        allClear: 'Every task is finished and reported.',
        // Info only, never a guard: issues whose fix is still running.
        info: validationIssues.filter((i) => i.status === 'fixing').length
          ? [`Still fixing: ${validationIssues.filter((i) => i.status === 'fixing')
            .map((i) => `VI-${i.number} ${i.title}`).join(', ')}`]
          : undefined,
        confirmLabel: transitionLabel('in_validation'),
        loading: detailedPlanLoading,
      };
    }
    if (confirmTo === 'released') {
      const blockers = releaseState?.blockers ?? [];
      const approved = deviations.find((d) => d.to_status === 'released' && d.status === 'approved');
      const pending = deviations.find((d) => d.to_status === 'released' && d.status === 'pending');
      const base = {
        to: confirmTo, title: transitionLabel('released'),
        consequence: 'Releasing puts the change live. It cannot be moved back; after release it can only be closed.',
        open: blockers,
        allClear: 'Validation, checklist and lessons are done.',
        confirmLabel: transitionLabel('released'),
        final: true,
        loading: !releaseState,
      };
      if (blockers.length === 0 || approved) {
        return approved && blockers.length > 0
          ? { ...base, info: [`Deviation #${approved.id} is approved: releasing uses it.`] }
          : base;
      }
      // Still open and no approved deviation: the dialog asks for one with the
      // reason (4-eyes), or says whose decision it now waits on.
      if (pending) {
        return { ...base, holdNote: `Deviation #${pending.id} is asked and waits for its approver. Release once it is approved.` };
      }
      return {
        ...base,
        title: 'Release with a deviation',
        consequence: 'Releasing puts the change live although the points below are still open. That needs a deviation: '
          + 'give the reason, someone other than you approves it, then the change can be released.',
        final: false,
        confirmLabel: 'Ask for a deviation',
        reason: { label: 'Why release anyway? (required, recorded)', placeholder: 'What covers the open points' },
        asksDeviation: true,
      };
    }
    if (confirmTo === 'approved') {
      return {
        to: confirmTo, title: transitionLabel('approved'),
        consequence: motherPlant ? plantText('mp.approveBody', change.mother_plant_name) : t('confirm.approveBody'),
        open: [],
        allClear: motherPlant ? t('mp.approveClear')
          : t(change.customer_relevant ? 'confirm.approveClear' : 'confirm.approveClearInternal'),
        confirmLabel: transitionLabel('approved'),
      };
    }
    if (confirmTo === 'closed') {
      return {
        to: confirmTo, title: transitionLabel('closed'),
        consequence: 'Closing is final. The change and its records become read only.',
        open: [], confirmLabel: transitionLabel('closed'), final: true,
      };
    }
    // Any other step asked here reads by its own verb, never another step's.
    const verb = transitionLabel(confirmTo, change.status);
    return { to: confirmTo, title: verb, consequence: `${verb}: this step is recorded in the audit trail.`,
      open: [], confirmLabel: verb };
  })();

  const tabButton = (tb: Tab, governance: boolean) => {
    const locked = !governance && tabLocked(tb);
    const selected = effectiveTab === tb;
    const isActivePhase = !governance && !locked && !stopped
      && activeTabsFor(change.status, change.customer_relevant, change.origin).includes(tb);
    // Scoping leaves two jobs on the impact tab: pick the impacted items,
    // then confirm the set. Both are done when the confirmation lands.
    const openWork = tb === 'impacted' && change.status === 'scoping' && !change.impact_confirmed_at;
    const lockReason = locked ? t(stoppedLocked(tb) ? 'tab.lockedStopped' : lockedTitleKey(tb)) : null;
    const state = openWork ? t('tab.openWork') : isActivePhase ? t('tab.activePhase') : null;
    const label = governance ? changeTabLabel(tb)
      : changeTabLabel(tb, change.customer_relevant, change.status, change.mother_plant_name);
    return (
      <div key={tb} className="group relative shrink-0">
        <button type="button" role="tab" id={`${tabsId}-tab-${tb}`}
          aria-selected={selected} aria-controls={`${tabsId}-panel`} tabIndex={selected ? 0 : -1}
          aria-disabled={locked || undefined}
          aria-describedby={lockReason ? `${tabsId}-why-${tb}` : undefined}
          title={lockReason ? undefined : state ?? undefined}
          className={`-mb-px inline-flex items-center gap-1.5 border-b-2 pb-2 pt-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 ${
            governance ? 'text-[13px] ' : ''}${
            locked ? 'border-transparent text-slate-600 cursor-not-allowed'
            : selected ? 'border-sky-400 text-sky-300 font-medium'
            : 'border-transparent text-slate-400 hover:text-slate-200'}`}
          onClick={() => { if (!locked) setTab(tb); }}>
          {isActivePhase && (
            <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-emerald-400 motion-safe:animate-pulse" />
          )}
          {openWork && (
            <span aria-hidden="true" data-testid="tab-open-work"
              className="h-1.5 w-1.5 rounded-full bg-lime-400 ring-1 ring-lime-300/50" />
          )}
          {locked && <Lock aria-hidden="true" size={11} className="shrink-0" />}
          {label}
          {state && <span className="sr-only">, {state}</span>}
        </button>
        {lockReason && (
          <span role="tooltip" id={`${tabsId}-why-${tb}`} data-testid={`tab-why-${tb}`}
            className="pointer-events-none absolute left-0 top-full z-30 mt-1 hidden w-max max-w-[16rem] rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200 shadow-lift group-hover:block group-focus-within:block">
            {lockReason}
          </span>
        )}
      </div>
    );
  };
  // Arrow keys move between tabs (roving focus); Enter or Space opens one.
  const onTabKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
    const list = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    const n = e.key === 'Home' ? 0 : e.key === 'End' ? list.length - 1
      : (at + (e.key === 'ArrowRight' ? 1 : -1) + list.length) % list.length;
    e.preventDefault();
    list[n]?.focus();
  };

  const isOverview = effectiveTab === 'overview';
  // Closed and canceled changes are records: nothing on them is editable.
  const readOnly = change.status === 'closed' || change.status === 'cancelled';
  const closedOn = change.status === 'closed'
    ? [...(changelog ?? [])].reverse().find((e) => e.field_name === 'status'
      && decodeLogValue(e.new_value) === 'closed')?.performed_at ?? null
    : null;
  const cockpitProps = {
    change, gates, pendingDeviations, impl,
    onAdvance: advance,
    advancing: transition.isPending,
    onResolveGate: () => setTab('d1'),
    onShowImpact: () => setTab('impacted'),
    actions: myActions?.actions ?? [],
    onAction: goTab,
    canRecordMeeting, canSeeGovernance,
    // What the change is waiting on: same list for every viewer, whoever
    // owns the next move.
    waits: earlyStageWaits(change, resolveWaitStates(change, concerns, deptName, change.assessments,
      { state: implState, escalations: implEscalations }, validation,
      change.status === 'approved' ? planFeedback : null,
      { openPlanDeviations, releaseBlockers: releaseState?.blockers ?? null, validationIssues,
        revisionsInCheck: revisionsInCheckOf(impl?.items) }),
      stage?.waits, { concerns, assessments: change.assessments, departmentName: deptName }),
    onGo: goTab,
    needs,
    warns: (step: string) => (step === 'to:quoting' ? costingWarning : null),
    assessment: assessmentState,
    may,
    review: review ?? null,
    onStepAction: (key: string) => {
      if (key === 'override-costing') setOverrideOpen(true);
    },
    onDecideDeviation: (id?: number) => { setTab('overview'); setFocusDeviation(id ?? null); },
    deviationTargets: {
      approved: deviations.filter((d) => d.status === 'approved').map((d) => d.to_status),
      pending: deviations.filter((d) => d.status === 'pending').map((d) => d.to_status),
    },
    // A gate held step: the deviation banner asks for the deviation (the
    // gate is a soft guard; an approved one lets the step through).
    onAskDeviation: (to: ChangeStatus, gateKey: GateKey) => {
      const g = gates.find((x) => x.gate_key === gateKey);
      setBlocked({ to, reason: `${t('gate.' + gateKey)} ${t('cockpit.gateWord')} ${
        gateStateText(g?.decision)}. `
        + 'An approved deviation is required to proceed.' });
      setBlockedSeq((n) => n + 1);
    },
    leadSlot: <LeadPicker change={change}
      canEdit={!['closed', 'cancelled', 'rejected', 'released'].includes(change.status)
        && (isAdmin || isChangeLead || isPmMember)}
      viewer={!actingAs && userId != null ? { id: userId, name: t('cockpit.leadMe') } : null}
      isAdmin={isAdmin} />,
  };

  // "More actions" menu keys: Escape closes it and gives focus back to its
  // button; the arrow keys (Home, End) move between the items.
  const onMoreKey = (e: React.KeyboardEvent<HTMLDetailsElement>) => {
    const el = e.currentTarget;
    const summary = el.querySelector<HTMLElement>('summary');
    if (e.key === 'Escape' && el.open) {
      e.preventDefault(); e.stopPropagation();
      el.open = false; summary?.focus();
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
    const items = Array.from(el.querySelectorAll<HTMLElement>('[role="menuitem"]'));
    if (items.length === 0) return;
    e.preventDefault();
    if (!el.open) el.open = true;
    const at = items.indexOf(document.activeElement as HTMLElement);
    const n = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1
      : at === -1 ? (e.key === 'ArrowUp' ? items.length - 1 : 0)
      : (at + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[n]?.focus();
  };
  // Rare and destructive moves live behind "More actions", not beside the title.
  const canCancel = CANCELLABLE.includes(change.status) && may('cancelled');
  const headerActions = (
    <div className="flex shrink-0 items-center gap-2">
      {change.status === 'rejected' && may('scoping') && (
        <button type="button" data-testid="header-reopen" className={btnSm.secondary}
          onClick={() => setReopenOpen(true)}>{transitionLabel('scoping', 'rejected')}</button>
      )}
      {/* Only once the changelog says where the hold came from: before that
          resumeTo is a guess. */}
      {change.status === 'on_hold' && changelog !== undefined && may(resumeTo) && (
        <button type="button" className={btnSm.secondary}
          onClick={() => advance(resumeTo)}>{transitionLabel(resumeTo, 'on_hold')}</button>
      )}
      {canCancel && (
        <details ref={moreRef} className="relative"
          onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) e.currentTarget.open = false; }}
          onKeyDown={onMoreKey}>
          <summary aria-label={t('change.moreActions')} title={t('change.moreActions')}
            className={`${btnIcon} cursor-pointer list-none [&::-webkit-details-marker]:hidden`}>
            <MoreHorizontal aria-hidden="true" size={18} />
          </summary>
          <div role="menu" className="absolute right-0 z-30 mt-1 w-48 rounded-lg border border-slate-700 bg-slate-800 p-1 shadow-lift">
            <button type="button" role="menuitem" data-testid="header-cancel"
              className="w-full rounded-md px-3 py-2 text-left text-sm text-red-300 hover:bg-red-950/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
              onClick={() => {
                if (moreRef.current) {
                  moreRef.current.open = false;
                  moreRef.current.querySelector<HTMLElement>('summary')?.focus();
                }
                advance('cancelled');
              }}>
              {transitionLabel('cancelled')}…
            </button>
          </div>
        </details>
      )}
    </div>
  );
  const project = projectLabel(change.project_number, change.project_name);

  return (
    // One width for every tab, so switching tabs never moves the header.
    <div className="max-w-[1400px] mx-auto px-6 pb-6 pt-4">
      <a href="#change-main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-slate-800 focus:px-3 focus:py-2 focus:text-sm focus:text-sky-200 focus:ring-2 focus:ring-sky-400">
        Skip to the tab content
      </a>
      {isOverview ? (
        <div className="flex items-start justify-between gap-4 pt-2 mb-3">
          <h1 className="text-2xl font-semibold text-balance flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>
              <span className="font-mono text-slate-400">{change.change_number}</span> · {change.title}
              {/* Which project this belongs to, one line under the name. */}
              {project && (
                <Link data-testid="change-project"
                  to={`/projects/${change.project_id}`}
                  className="block text-sm font-normal text-slate-400 hover:text-sky-300">
                  {project}
                </Link>
              )}
            </span>
            {impl?.ready_to_go && (
              <span className="inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-900 text-emerald-100">
                <Check aria-hidden="true" size={12} />{t('impl.readyToGo')}
              </span>
            )}
          </h1>
          {headerActions}
        </div>
      ) : (
        // Every other tab: one slim bar that stays put while the tab scrolls.
        <div data-testid="change-bar"
          className="sticky top-0 z-20 -mx-6 mb-3 flex min-h-14 flex-wrap items-center gap-x-3 gap-y-1 border-b border-slate-800 bg-slate-900 px-6 py-2">
          <h1 className="flex min-w-0 max-w-[40%] items-baseline gap-2 text-base font-semibold">
            <span className="shrink-0 font-mono text-slate-400">{change.change_number}</span>
            <span className="truncate text-slate-100" title={project ? `${change.title} (${project})` : change.title}>
              {change.title}
            </span>
          </h1>
          <CockpitSummary {...cockpitProps} variant="compact" onShowOverview={() => setTab('overview')} />
          {headerActions}
        </div>
      )}

      {isOverview && (
        <LifecycleStepper status={change.status} customerRelevant={change.customer_relevant}
          origin={change.origin}
          end={stopped ? { kind: stopped.kind, stoppedAt: stopped.at, closed: change.status === 'closed' } : null} />
      )}

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
      {readOnly && (
        <p role="status" data-testid="closed-banner"
          className="mt-3 flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/60 px-4 py-2 text-sm text-slate-300">
          <Lock aria-hidden="true" size={14} className="shrink-0 text-slate-400" />
          {change.status === 'closed'
            ? t('change.closedBanner').replace('{d}', closedOn ? ` ${formatDate(closedOn)}` : '')
            : t('change.canceledBanner')}
        </p>
      )}

      {blocked && (
        <DeviationBanner
          changeId={changeId}
          blockedTo={blocked.to}
          from={change.status}
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
      <TransitionConfirmDialog confirm={confirm} busy={transition.isPending || askDeviation.isPending}
        onClose={() => setConfirmTo(null)}
        onConfirm={(reason) => {
          const to = confirmTo!; setConfirmTo(null);
          if (confirm?.asksDeviation && reason) { askDeviation.mutate({ to, reason }); return; }
          transition.mutate(reason ? { to, reason } : { to });
        }}>
        {motherPlant && change.status === 'captured' && confirmTo === 'scoping'
          && !change.description?.trim() && (canEditDescription || canRunMotherPlant) && (
          <div data-testid="kickoff-description" className="mt-3 text-sm">
            <DescriptionEditor change={change} canEdit />
          </div>
        )}
      </TransitionConfirmDialog>
      <ReasonDialog
        open={overrideOpen}
        title={t('next.override')}
        warning={t('confirm.overrideBody')}
        label={t('confirm.overrideLabel')}
        submitLabel={t('confirm.overrideGo')}
        onSubmit={(reason) => { setOverrideOpen(false); override.mutate(reason); }}
        onClose={() => setOverrideOpen(false)}
      />
      <ReasonDialog
        open={cancelOpen}
        title="Cancel change"
        warning={t('confirm.cancelFinal')}
        label="Why is this change cancelled? (required, audited)"
        submitLabel="Cancel change for good"
        danger
        onSubmit={(reason) => { setCancelOpen(false); transition.mutate({ to: 'cancelled', cancellation_reason: reason }); }}
        onClose={() => setCancelOpen(false)}
      />

      {isOverview && <CockpitSummary {...cockpitProps} />}

      {/* Tabs: a real tablist. A locked tab stays focusable and says why,
          on hover and on keyboard focus, not only in a mouse tooltip. */}
      <div role="tablist" aria-label={t('change.tabs')} onKeyDown={onTabKey}
        className="mb-4 flex flex-nowrap items-end gap-x-4 overflow-x-auto border-b border-slate-700 text-sm sm:flex-wrap sm:overflow-visible">
        {everydayTabs.map((tb) => tabButton(tb, false))}
        {canSeeGovernance && (
          <>
            <span aria-hidden="true" className="ml-auto mb-2.5 h-4 w-px bg-slate-700" />
            <span className="mb-2 text-[11px] text-slate-500">{t('change.governance')}</span>
            {GOVERNANCE_TABS.map((tb) => tabButton(tb, true))}
          </>
        )}
      </div>

      <div id={`${tabsId}-panel`} role="tabpanel" tabIndex={-1}
        aria-labelledby={`${tabsId}-tab-${effectiveTab}`}>
        <span id="change-main" className="sr-only" tabIndex={-1} />
      {effectiveTab === 'overview' && (
        <div className="space-y-2 text-sm">
          <TransitionDeviationsPanel changeId={changeId} deviations={deviations}
            decidableIds={(myActions?.actions ?? []).filter((a) => a.kind === 'deviation_decision')
              .map((a) => a.deviation_id).filter((x): x is number => x != null)}
            focusId={focusDeviation} onFocused={() => setFocusDeviation(undefined)} />
          <p><span className="text-slate-400">Type:</span> {changeTypeLabel(change.change_type)}</p>
          <p className="flex items-center gap-2">
            <span className="text-slate-400">Priority:</span>
            <PriorityEditor change={change} canEdit={!readOnly && (isAdmin || isChangeLead)} />
          </p>
          <p><span className="text-slate-400">Reason:</span> {change.reason ?? '-'}</p>
          <DescriptionEditor change={change} canEdit={canEditDescription} />
          {/* A mother-plant change is never customer relevant here. */}
          {!motherPlant && <CustomerRelevantEditor change={change} canEdit={isAdmin || isChangeLead} />}

          {/* Customer correspondence sits above the document lists: it is what
              everyone comes looking for, and it belongs to no phase. */}
          <div className="pt-3">
            <CustomerMailLog changeId={change.id} attachments={change.attachments ?? []} readOnly={readOnly} />
          </div>

          <ChangeAttachments change={change} readOnly={readOnly} />
        </div>
      )}

      {effectiveTab === 'scoping' && change && (
        <ScopingPanel change={change}
          canSendRejection={!myActions ? true : isSalesMember}
          canAnswerConcerns={isSalesMember} isPm={isPmMember}
          canRecordMeeting={canRecordMeeting}
          onInformTeam={motherPlant ? () => setTab('mother') : undefined}
          myDepartmentIds={myActions?.memberships ?? []} />
      )}

      {effectiveTab === 'impacted' && change && (
        <ImpactTree changeId={change.id} status={change.status} origin={change.origin}
          impactConfirmedByName={change.impact_confirmed_by_name}
          impactConfirmedAt={change.impact_confirmed_at}
          canConfirm={canConfirmImpact}
          // Lead, PM and admin edit the set; Development picks it too while it
          // is at scoping and not locked, then confirms it. The backend's
          // can_edit_impact is the answer; the fallback mirrors it.
          canEdit={stage ? stage.can_edit_impact : (isAdmin || isChangeLead || isPmMember
            || (isDevelopmentMember && change.status === 'scoping' && !change.impact_confirmed_at))}
          titleAuto={stage?.title_auto ?? change.title_auto}
          scopeChangedAfterQuote={change.scope_changed_after_quote
            ?? (stage?.scope_change ? !stage.scope_change.covered : false)}
          quoted={stage?.impact_edit_needs_reason
            ?? ['quoted', 'approved', 'in_implementation', 'in_validation', 'released'].includes(change.status)}
          onChanged={() => qc.invalidateQueries({ queryKey: ['change', changeId] })} />
      )}

      {effectiveTab === 'review' && (hasReview || change.origin === 'engineering_review') && (
        <ReviewTab change={change} onGoImpact={() => setTab('impacted')} />
      )}

      {effectiveTab === 'mother' && motherPlant && (
        <MotherPlantTab change={change} departments={departments} />
      )}

      {effectiveTab === 'timing' && change && (
        <TimingTab change={change} departments={departments}
          myDepartmentIds={myActions?.memberships ?? []}
          canEditPlan={canEditPlan} canPublish={canPublishTiming} canSeeAll={canSeeCosts}
          canSetBankBuild={canSetBankBuild} canDecideDeviation={canDecideDeviation} isAdmin={isAdmin}
          canInformMotherPlant={canRunMotherPlant}
          issues={change.status === 'in_implementation' && validationIssues.length > 0 ? (
            <IssuesPanel changeId={change.id} changeStatus={change.status} departments={departments}
              title="Validation issues / recovery"
              hint="The change is back in implementation to fix these. The recovery blocks are in the plan below; once the fix is done, validation starts again."
              viewer={{
                id: actingAs ? null : userId, isAdmin, canManage: canManageRelease, isSales: isSalesMember,
                canSeeCosts, myDepartmentIds: myActions?.memberships ?? [],
              }}
              canRaise={canManageRelease}
              releaseDueDate={change.release_due_date} focusIssueId={focusIssueId} />
          ) : undefined} />
      )}

      {effectiveTab === 'release' && change && (
        <ReleaseTab change={change} departments={departments}
          myDepartmentIds={myActions?.memberships ?? []}
          canSeeAll={canSeeCosts} canAcknowledge={canPublishPlan}
          canManage={canManageRelease}
          viewerId={actingAs ? null : userId} isAdmin={isAdmin} isSales={isSalesMember}
          onAdvance={advance} advancing={transition.isPending} focusIssueId={focusIssueId} />
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
            userId={userId ?? null} isChangeLead={isChangeLead}
            declinedIds={stage?.assessment?.declined_pending.map((d) => d.department_id)}
            round={assessmentState} />
        </div>
      )}

      {effectiveTab === 'costing' && (
        <div className="space-y-3 text-sm">
          {/* The tab names itself; while departments price, one line says how costing works. */}
          {change.status === 'costing' && (
            <p data-testid="costing-stage" className="text-xs text-slate-400">{t('costing.stageBody')}</p>
          )}
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
          {/* The P&L reads /summation, which only the cost roles may: anyone
              else gets their own department's actual costs only, and no
              request that can only 403. */}
          <PnlCard change={change} departments={departments} canSeeCosts={canSeeCosts} />
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
                .map((p) => ({ id: p.id, name: p.name, is_active: p.is_active, code: p.code, location: p.location }))}
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
        <AuditTimeline correlationId={change.change_number} changeId={change.id} />
      )}
      </div>
    </div>
  );
}
