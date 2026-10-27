/**
 * A person as the team surfaces show them (2026-10-26): full name, the email
 * as a mailto link underneath, an optional badge and an optional remove
 * button. Used by the project team dialog and the Departments admin page.
 */
import type { ReactNode } from 'react';
import { X } from 'lucide-react';
import { mailAddress } from '../../lib/mailAddress';

export default function PersonDetail({ name, email, badge, inactive, onRemove, removeLabel, 'data-testid': testId }: {
  name: string;
  email?: string | null;
  badge?: ReactNode;
  inactive?: boolean;
  onRemove?: () => void;
  removeLabel?: string;
  'data-testid'?: string;
}) {
  const mail = mailAddress(email);
  return (
    <span data-testid={testId}
      className={`inline-flex max-w-full items-start gap-2 rounded-lg border border-slate-700 bg-slate-900/60 px-2.5 py-1.5 ${inactive ? 'opacity-60' : ''}`}>
      <span className="min-w-0">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-medium text-slate-100">{name}</span>
          {badge}
        </span>
        {mail && (
          <a href={`mailto:${mail}`} className="block truncate text-xs text-sky-400 hover:text-sky-300 hover:underline">
            {mail}
          </a>
        )}
      </span>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={removeLabel ?? `Remove ${name}`}
          className="-mr-1 mt-0.5 rounded p-0.5 text-slate-500 hover:bg-slate-700 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400">
          <X aria-hidden="true" size={14} />
        </button>
      )}
    </span>
  );
}
