import { Clock, CheckCircle, RefreshCw, Loader2, ChevronRight, RotateCcw } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';

const TYPE_PILL = {
  'REST-to-REST': 'bg-sky-100 text-sky-700',
  'REST-to-SOAP': 'bg-purple-100 text-purple-700',
  'SOAP-to-REST': 'bg-violet-100 text-violet-700',
  'File-based':   'bg-amber-100 text-amber-700',
};

export default function ApprovalQueue({
  approvals, selectedId, onSelect,
  rejected, onRegenerate,
  isLoading, isRegenerating,
}) {
  const queryClient = useQueryClient();

  return (
    <div className="w-[280px] min-w-[280px] bg-white rounded-xl border border-zinc-200 overflow-hidden flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-zinc-100 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-2">
          <Clock size={14} className="text-zinc-400" />
          <span
            className="font-semibold text-zinc-900 text-sm"
            style={{ fontFamily: 'Outfit, sans-serif' }}
          >
            Pending
          </span>
          {approvals.length > 0 && (
            <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-100 text-amber-700 text-xs font-bold">
              {approvals.length}
            </span>
          )}
        </div>
        <button
          onClick={() => queryClient.invalidateQueries({ queryKey: ['approvals', 'pending'] })}
          title="Refresh"
          className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-600 hover:bg-zinc-100 transition-colors"
        >
          <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Queue list */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {isLoading ? (
          <div className="flex justify-center py-10">
            <Loader2 size={20} className="animate-spin text-zinc-300" />
          </div>
        ) : approvals.length === 0 && rejected.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <CheckCircle size={28} className="text-zinc-200 mx-auto mb-2" />
            <p className="text-sm text-zinc-400">No pending approvals</p>
          </div>
        ) : (
          <div>
            {approvals.map(a => {
              const isSelected = selectedId === a.id;
              const typeCls = TYPE_PILL[a.type] ?? 'bg-zinc-100 text-zinc-600';
              return (
                <button
                  key={a.id}
                  onClick={() => onSelect(a.id)}
                  className={`w-full text-left px-4 py-3.5 border-b border-zinc-100 last:border-0 transition-colors flex items-center justify-between gap-2 ${
                    isSelected
                      ? 'bg-sky-50 border-l-2 border-l-sky-500 pl-3.5'
                      : 'hover:bg-zinc-50'
                  }`}
                >
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-zinc-900 truncate leading-tight">
                      {a.name || a.id}
                    </p>
                    <p className="text-xs font-mono text-zinc-400 mt-0.5 truncate">{a.id}</p>
                    {a.type && (
                      <span className={`inline-block mt-1.5 px-2 py-0.5 rounded-full text-xs font-medium ${typeCls}`}>
                        {a.type}
                      </span>
                    )}
                  </div>
                  <ChevronRight
                    size={13}
                    className={`flex-shrink-0 ${isSelected ? 'text-sky-500' : 'text-zinc-300'}`}
                  />
                </button>
              );
            })}
          </div>
        )}

        {/* Rejected — available for regeneration */}
        {rejected.length > 0 && (
          <div className="border-t border-zinc-200 p-3">
            <p className="text-[10px] font-semibold text-zinc-500 uppercase tracking-wider mb-2 px-1">
              Rejected ({rejected.length})
            </p>
            <div className="space-y-2">
              {rejected.map(a => (
                <div key={a.id} className="p-3 rounded-lg bg-rose-50 border border-rose-100">
                  <p className="text-xs font-medium text-zinc-700 truncate mb-2">{a.name || a.id}</p>
                  <button
                    onClick={() => onRegenerate(a.id)}
                    disabled={isRegenerating}
                    className="w-full flex items-center justify-center gap-1.5 py-1.5 bg-rose-600 text-white rounded-md text-xs font-semibold hover:bg-rose-700 disabled:opacity-50 transition-colors"
                  >
                    <RotateCcw size={11} />
                    {isRegenerating ? 'Regenerating…' : 'Regenerate'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
