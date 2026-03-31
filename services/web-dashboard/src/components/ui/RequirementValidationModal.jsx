import { useState } from 'react';
import { X, AlertTriangle, CheckCircle, ChevronDown, ChevronUp } from 'lucide-react';

/**
 * RequirementValidationModal — shown when source/target could not be extracted.
 *
 * Props:
 *   requirements  – full array of Requirement objects from GET /api/v1/requirements
 *   onContinue    – (fieldOverrides: Record<req_id, {source_system?, target_system?}>) => void
 *   onCancel      – () => void
 */

function isIncomplete(val) {
  return !val || val.trim() === '' || val.trim().toLowerCase() === 'unknown';
}

const inputCls =
  'w-full px-3 py-1.5 text-sm border border-amber-300 rounded-lg outline-none ' +
  'focus:border-indigo-400 focus:ring-2 focus:ring-indigo-100 bg-white transition-all';

export default function RequirementValidationModal({ requirements, onContinue, onCancel }) {
  // Group all requirements by source+target pair; keep only incomplete pairs
  const pairsMap = {};
  for (const req of requirements) {
    const key = `${req.source_system}|||${req.target_system}`;
    if (!pairsMap[key]) {
      pairsMap[key] = {
        key,
        originalSource: req.source_system,
        originalTarget: req.target_system,
        reqs: [],
      };
    }
    pairsMap[key].reqs.push(req);
  }

  const incompletePairs = Object.values(pairsMap).filter(
    (p) => isIncomplete(p.originalSource) || isIncomplete(p.originalTarget),
  );

  const [edits, setEdits] = useState(() => {
    const init = {};
    for (const p of incompletePairs) {
      init[p.key] = {
        source: isIncomplete(p.originalSource) ? '' : p.originalSource,
        target: isIncomplete(p.originalTarget) ? '' : p.originalTarget,
      };
    }
    return init;
  });

  const [expanded, setExpanded] = useState({});

  const handleEdit = (pairKey, field, value) => {
    setEdits((prev) => ({ ...prev, [pairKey]: { ...prev[pairKey], [field]: value } }));
  };

  const handleContinue = () => {
    const overrides = {};
    for (const pair of incompletePairs) {
      const edit = edits[pair.key] || {};
      const newSource = edit.source?.trim() ?? '';
      const newTarget = edit.target?.trim() ?? '';
      if (newSource || newTarget) {
        for (const req of pair.reqs) {
          overrides[req.req_id] = {};
          if (newSource) overrides[req.req_id].source_system = newSource;
          if (newTarget) overrides[req.req_id].target_system = newTarget;
        }
      }
    }
    onContinue(overrides);
  };

  const totalAffected = incompletePairs.reduce((sum, p) => sum + p.reqs.length, 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl border border-slate-200 overflow-hidden max-h-[90vh] flex flex-col">

        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-amber-100 bg-amber-50/60">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-full bg-amber-100 border border-amber-200 flex items-center justify-center shrink-0">
              <AlertTriangle size={16} className="text-amber-600" />
            </div>
            <div>
              <h2
                className="font-bold text-slate-900 text-base"
                style={{ fontFamily: 'Outfit, sans-serif' }}
              >
                Validate Source &amp; Target Systems
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {incompletePairs.length} integration pair{incompletePairs.length !== 1 ? 's' : ''}{' '}
                ({totalAffected} requirement{totalAffected !== 1 ? 's' : ''}) with missing system
                info — fill in what you know.
              </p>
            </div>
          </div>
          <button
            onClick={onCancel}
            className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-4">
          {incompletePairs.map((pair) => {
            const edit = edits[pair.key] || {};
            const isExpanded = expanded[pair.key];
            const visibleReqs = isExpanded ? pair.reqs : pair.reqs.slice(0, 2);
            const sourceIncomplete = isIncomplete(pair.originalSource);
            const targetIncomplete = isIncomplete(pair.originalTarget);

            return (
              <div
                key={pair.key}
                className="border border-amber-200 rounded-xl overflow-hidden bg-amber-50/20"
              >
                {/* Pair label */}
                <div className="px-4 py-2.5 bg-amber-50 border-b border-amber-100 flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-700">
                    {sourceIncomplete ? (
                      <span className="text-amber-600 italic">unknown source</span>
                    ) : (
                      pair.originalSource
                    )}
                    <span className="mx-1.5 text-slate-400">→</span>
                    {targetIncomplete ? (
                      <span className="text-amber-600 italic">unknown target</span>
                    ) : (
                      pair.originalTarget
                    )}
                  </span>
                  <span className="ml-auto text-xs text-slate-400 shrink-0">
                    {pair.reqs.length} req{pair.reqs.length !== 1 ? 's' : ''}
                  </span>
                </div>

                {/* Editable fields */}
                <div className="px-4 py-3 grid grid-cols-2 gap-3">
                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Source System
                      {sourceIncomplete && (
                        <span className="ml-1 text-amber-500">missing</span>
                      )}
                    </label>
                    {sourceIncomplete ? (
                      <input
                        type="text"
                        placeholder="e.g. SAP, ERP, PLM…"
                        value={edit.source || ''}
                        onChange={(e) => handleEdit(pair.key, 'source', e.target.value)}
                        className={inputCls}
                      />
                    ) : (
                      <div className="px-3 py-1.5 text-sm text-slate-700 bg-slate-100 rounded-lg">
                        {pair.originalSource}
                      </div>
                    )}
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Target System
                      {targetIncomplete && (
                        <span className="ml-1 text-amber-500">missing</span>
                      )}
                    </label>
                    {targetIncomplete ? (
                      <input
                        type="text"
                        placeholder="e.g. Salsify, PIM, CRM…"
                        value={edit.target || ''}
                        onChange={(e) => handleEdit(pair.key, 'target', e.target.value)}
                        className={inputCls}
                      />
                    ) : (
                      <div className="px-3 py-1.5 text-sm text-slate-700 bg-slate-100 rounded-lg">
                        {pair.originalTarget}
                      </div>
                    )}
                  </div>
                </div>

                {/* Affected requirements list */}
                <div className="px-4 pb-3 space-y-0.5">
                  <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1.5">
                    Affected Requirements
                  </p>
                  {visibleReqs.map((req) => (
                    <div key={req.req_id} className="flex items-start gap-2 text-xs py-0.5">
                      <span className="font-mono text-slate-400 shrink-0 w-24 truncate">
                        {req.req_id}
                      </span>
                      <span className="text-slate-600 truncate" title={req.description}>
                        {req.description || '—'}
                      </span>
                    </div>
                  ))}
                  {pair.reqs.length > 2 && (
                    <button
                      onClick={() =>
                        setExpanded((prev) => ({ ...prev, [pair.key]: !isExpanded }))
                      }
                      className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 mt-1.5 transition-colors"
                    >
                      {isExpanded ? (
                        <><ChevronUp size={11} /> Show less</>
                      ) : (
                        <><ChevronDown size={11} /> +{pair.reqs.length - 2} more</>
                      )}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-slate-100 bg-slate-50/40">
          <p className="text-xs text-slate-400">
            All fields are optional — you can continue without filling them.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={onCancel}
              className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleContinue}
              className="flex items-center gap-2 px-5 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
            >
              <CheckCircle size={14} /> Continue
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
