import { useState } from 'react';
import { Trash2, AlertTriangle, Loader2, CheckCircle, Database, FileText, Server } from 'lucide-react';
import { API } from '../../api.js';

const RESET_ACTIONS = [
  {
    id: 'requirements',
    label: 'Reset Requirements',
    description: 'Clear uploaded CSV data and agent logs. Client project codes are NOT cleared — use Reset MongoDB to free up project codes.',
    icon: FileText,
    colorKey: 'amber',
    confirm: 'Delete requirements and logs?',
  },
  {
    id: 'mongodb',
    label: 'Reset MongoDB',
    description: 'Wipe all integrations, approvals, documents, and client project codes from the database. Use this to reuse a project prefix.',
    icon: Database,
    colorKey: 'orange',
    confirm: 'Wipe all MongoDB data including client project codes?',
  },
  {
    id: 'chromadb',
    label: 'Reset ChromaDB',
    description: 'Recreate the RAG vector collection. All approved examples will be permanently lost.',
    icon: Server,
    colorKey: 'red',
    confirm: 'Destroy ChromaDB vector collection?',
  },
  {
    id: 'all',
    label: 'Full Reset',
    description: 'Nuclear option: clears requirements, MongoDB, and ChromaDB simultaneously.',
    icon: Trash2,
    colorKey: 'rose',
    confirm: 'Perform FULL system reset? This cannot be undone.',
  },
];

const COLORS = {
  amber:  { border: 'border-amber-200',  icon: 'text-amber-600 bg-amber-50',   btn: 'bg-amber-600 hover:bg-amber-700',   warn: 'bg-amber-50 text-amber-800 border-amber-200' },
  orange: { border: 'border-orange-200', icon: 'text-orange-600 bg-orange-50', btn: 'bg-orange-600 hover:bg-orange-700', warn: 'bg-orange-50 text-orange-800 border-orange-200' },
  red:    { border: 'border-red-200',    icon: 'text-red-600 bg-red-50',       btn: 'bg-red-600 hover:bg-red-700',       warn: 'bg-red-50 text-red-800 border-red-200' },
  rose:   { border: 'border-rose-300',   icon: 'text-rose-700 bg-rose-50',     btn: 'bg-rose-700 hover:bg-rose-800',     warn: 'bg-rose-50 text-rose-800 border-rose-300' },
};

function ResetCard({ action }) {
  const [step, setStep]   = useState('idle'); // idle | confirm | loading | done | error
  const [msg, setMsg]     = useState('');
  const colors            = COLORS[action.colorKey];
  const Icon              = action.icon;

  const execute = async () => {
    setStep('loading');
    try {
      const res  = await API.admin.reset(action.id);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || `Reset failed (${res.status})`);
      setMsg(data.message || 'Reset complete');
      setStep('done');
      // Reload the app so all pages discard stale in-memory state
      setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
      setMsg(e.message || 'Reset failed');
      setStep('error');
    }
  };

  return (
    <div className={`bg-white rounded-2xl border ${colors.border} shadow-sm overflow-hidden`}>
      <div className="p-5 space-y-4">
        <div className="flex items-start gap-3">
          <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${colors.icon}`}>
            <Icon size={16} />
          </div>
          <div>
            <h3
              className="font-semibold text-slate-900"
              style={{ fontFamily: 'Outfit, sans-serif' }}
            >
              {action.label}
            </h3>
            <p className="text-sm text-slate-500 mt-0.5 leading-relaxed">{action.description}</p>
          </div>
        </div>

        {step === 'done' && (
          <div className="flex items-center gap-2 text-emerald-700 text-sm bg-emerald-50 border border-emerald-200 rounded-xl px-3 py-2">
            <CheckCircle size={14} /> {msg}
          </div>
        )}
        {step === 'error' && (
          <div className="flex items-center gap-2 text-rose-700 text-sm bg-rose-50 border border-rose-200 rounded-xl px-3 py-2">
            <AlertTriangle size={14} /> {msg}
          </div>
        )}

        {step === 'confirm' ? (
          <div className="space-y-3">
            <div className={`flex items-center gap-2 text-sm border rounded-xl px-3 py-2 ${colors.warn}`}>
              <AlertTriangle size={14} className="flex-shrink-0" />
              {action.confirm}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={execute}
                className={`flex items-center gap-2 px-4 py-2 text-white rounded-xl text-sm font-semibold transition-colors ${colors.btn}`}
              >
                Confirm Reset
              </button>
              <button
                onClick={() => setStep('idle')}
                className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : step === 'loading' ? (
          <div className="flex items-center gap-2 text-slate-500 text-sm">
            <Loader2 size={14} className="animate-spin" /> Resetting…
          </div>
        ) : step !== 'done' ? (
          <button
            onClick={() => setStep('confirm')}
            className={`flex items-center gap-2 px-4 py-2 text-white rounded-xl text-sm font-semibold transition-colors ${colors.btn}`}
          >
            <Trash2 size={13} />
            {action.label}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export default function ResetPage() {
  return (
    <div className="space-y-5 max-w-3xl">
      <div className="bg-amber-50 border border-amber-200 rounded-2xl p-4 flex items-start gap-3">
        <AlertTriangle size={17} className="text-amber-600 flex-shrink-0 mt-0.5" />
        <div>
          <p
            className="font-semibold text-amber-900"
            style={{ fontFamily: 'Outfit, sans-serif' }}
          >
            Danger Zone
          </p>
          <p className="text-sm text-amber-700 mt-0.5 leading-relaxed">
            These operations are destructive and cannot be undone.
            Each action requires explicit confirmation before execution.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {RESET_ACTIONS.map(action => (
          <ResetCard key={action.id} action={action} />
        ))}
      </div>
    </div>
  );
}
