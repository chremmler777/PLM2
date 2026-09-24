/**
 * DFM audit log helpers: plain-word action labels and colours, the four
 * filter groups (the API only filters by a single action, so the group
 * filter is applied client-side over the unfiltered page), and small
 * formatters (local date/time, file size, a short sha256 prefix).
 * Mirrors docs/superpowers/specs/2026-09-24-dfm-audit-api.md.
 */
import { KIND_LABELS, PARTY_LABELS, type DfmAuditAction, type DfmAuditEvent, type DfmParty } from '../../api/dfm';

export type DfmAuditGroup = 'all' | 'messages' | 'files' | 'topic' | 'views';

export const AUDIT_GROUP_LABELS: Record<DfmAuditGroup, string> = {
  all: 'All activity',
  messages: 'Messages',
  files: 'Files',
  topic: 'Topic changes',
  views: 'Views and downloads',
};
export const AUDIT_GROUPS: DfmAuditGroup[] = ['all', 'messages', 'files', 'topic', 'views'];

export function auditGroupOf(action: DfmAuditAction): Exclude<DfmAuditGroup, 'all'> {
  switch (action) {
    case 'topic_opened': case 'topic_closed': case 'topic_reopened': return 'topic';
    case 'entry_recorded': case 'entry_updated': return 'messages';
    case 'file_attached': return 'files';
    case 'file_viewed': case 'file_downloaded': return 'views';
  }
}

export function matchesAuditGroup(action: DfmAuditAction, group: DfmAuditGroup): boolean {
  return group === 'all' || auditGroupOf(action) === group;
}

/** Plain-word label and colour classes per action, for the badge/icon in the row. */
export const AUDIT_ACTION_STYLE: Record<DfmAuditAction, { label: string; badge: string; dot: string }> = {
  topic_opened: { label: 'Topic opened', badge: 'bg-emerald-500/15 text-emerald-200 ring-emerald-400/40', dot: 'bg-emerald-400' },
  topic_closed: { label: 'Topic finished', badge: 'bg-slate-600/40 text-slate-200 ring-slate-500', dot: 'bg-slate-400' },
  topic_reopened: { label: 'Topic reopened', badge: 'bg-amber-500/15 text-amber-200 ring-amber-400/40', dot: 'bg-amber-400' },
  entry_recorded: { label: 'Message recorded', badge: 'bg-blue-500/15 text-blue-200 ring-blue-400/40', dot: 'bg-blue-400' },
  entry_updated: { label: 'Message updated', badge: 'bg-blue-500/15 text-blue-200 ring-blue-400/40', dot: 'bg-blue-400' },
  file_attached: { label: 'File attached', badge: 'bg-violet-500/15 text-violet-200 ring-violet-400/40', dot: 'bg-violet-400' },
  file_viewed: { label: 'File viewed', badge: 'bg-cyan-500/15 text-cyan-200 ring-cyan-400/40', dot: 'bg-cyan-400' },
  file_downloaded: { label: 'File downloaded', badge: 'bg-teal-500/15 text-teal-200 ring-teal-400/40', dot: 'bg-teal-400' },
};

/** "24 Sep 2026, 11:15" from a UTC-without-offset backend timestamp, in the viewer's local time. */
export function auditLocalTime(iso: string): string {
  const d = new Date(iso.endsWith('Z') ? iso : `${iso}Z`);
  if (Number.isNaN(d.getTime())) return iso;
  const date = d.toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' });
  const time = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  return `${date}, ${time}`;
}

export function auditFileSize(bytes: number | undefined): string {
  if (bytes == null) return '';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let n = bytes / 1024;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n < 10 ? n.toFixed(1) : Math.round(n)} ${units[i]}`;
}

/** First 10 hex chars of a sha256, for the compact column; the full value goes in a title tooltip. */
export function auditShaShort(sha: string | null | undefined): string | null {
  if (!sha) return null;
  return sha.slice(0, 10);
}

const route = (party: DfmParty | undefined, to: DfmParty[] | undefined): string => {
  if (!party) return '';
  return `${PARTY_LABELS[party]} → ${(to ?? []).map((p) => PARTY_LABELS[p]).join(', ')}`;
};

/** One plain-word summary line for an event, used as a fallback / accessible text. */
export function auditSummary(e: DfmAuditEvent): string {
  const style = AUDIT_ACTION_STYLE[e.action];
  switch (e.action) {
    case 'entry_recorded':
    case 'entry_updated': {
      const kind = e.details.kind ? KIND_LABELS[e.details.kind] : '';
      return `${style.label} (${kind}) ${route(e.details.party, e.details.addressed_to)}`.trim();
    }
    case 'file_attached':
      return `${style.label}: ${e.details.filename ?? e.file?.filename ?? ''}`;
    case 'file_viewed':
    case 'file_downloaded':
      return `${style.label}: ${e.details.filename ?? e.file?.filename ?? ''}`;
    case 'topic_opened':
    case 'topic_closed':
    case 'topic_reopened':
      return `${style.label}: ${e.details.title ?? e.topic?.title ?? ''}`;
  }
}
