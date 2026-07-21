import { useState, useEffect } from 'react';

interface Props {
  open: boolean;
  title: string;
  label: string;
  submitLabel?: string;
  onSubmit: (reason: string) => void;
  onClose: () => void;
}

export default function ReasonDialog({ open, title, label, submitLabel = 'Submit', onSubmit, onClose }: Props) {
  const [reason, setReason] = useState('');
  useEffect(() => {
    if (open) setReason('');
  }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" role="dialog">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-5">
        <h3 className="text-base font-semibold mb-2">{title}</h3>
        <label className="block text-sm text-gray-600 mb-1">{label}</label>
        <textarea
          className="w-full border rounded-lg p-2 text-sm min-h-[80px]"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          autoFocus
        />
        <div className="flex justify-end gap-2 mt-4">
          <button className="px-3 py-1.5 text-sm border rounded-lg" onClick={onClose}>Cancel</button>
          <button
            className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white disabled:opacity-50"
            disabled={!reason.trim()}
            onClick={() => { onSubmit(reason.trim()); setReason(''); }}
          >{submitLabel}</button>
        </div>
      </div>
    </div>
  );
}
