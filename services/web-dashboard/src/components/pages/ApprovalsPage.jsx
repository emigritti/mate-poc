import { useState, useEffect } from 'react';
import { CheckCircle, XCircle, AlertCircle, Loader2, Clock, ChevronRight, RefreshCw } from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [content, setContent]       = useState('');
  const [feedback, setFeedback]     = useState('');
  const [rejectMode, setRejectMode] = useState(false);
  const [loading, setLoading]       = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError]           = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const [rejected, setRejected] = useState([]);         // rejected approvals available for regeneration
  const [regenerating, setRegenerating] = useState(null); // id currently being regenerated

  useEffect(() => { loadApprovals(); }, []);

  const loadApprovals = async () => {
    setLoading(true);
    try {
      const res  = await API.approvals.pending();
      const data = await res.json();
      // Backend returns { status, data: [...] }
      setApprovals(data.data || []);
    } catch {
      setError('Failed to load pending approvals');
    } finally {
      setLoading(false);
    }
  };

  const loadDocument = (id) => {
    setSelectedId(id);
    setRejectMode(false);
    setFeedback('');
    setError(null);
    setSuccessMsg(null);
    const approval = approvals.find(a => a.id === id);
    // Content is already in the approval object; adjust field name as needed
    setContent(approval?.content ?? approval?.document ?? '');
  };

  const handleApprove = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await API.approvals.approve(selectedId, content);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Approval failed (${res.status})`);
      }
      setSuccessMsg('Document staged. Use the Documents page to promote to Knowledge Base.');
      setApprovals(prev => prev.filter(a => a.id !== selectedId));
      setSelectedId(null);
    } catch (e) {
      setError(e.message || 'Approval failed — please try again');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReject = async () => {
    if (!feedback.trim()) {
      setError('Please provide rejection feedback before submitting');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const res = await API.approvals.reject(selectedId, feedback);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Rejection failed (${res.status})`);
      }
      setSuccessMsg('Document rejected — agent will retry with your feedback');
      setApprovals(prev => prev.filter(a => a.id !== selectedId));
      setRejected(prev => [
        ...prev,
        { ...approvals.find(a => a.id === selectedId), feedback },
      ]);
      setSelectedId(null);
    } catch (e) {
      setError(e.message || 'Rejection failed — please try again');
    } finally {
      setSubmitting(false);
    }
  };

  const handleRegenerate = async (approvalId) => {
    setRegenerating(approvalId);
    setError(null);
    setSuccessMsg(null);
    try {
      const res = await API.approvals.regenerate(approvalId);
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || `Regeneration failed (${res.status})`);
      }
      const data = await res.json();
      const newId = data.data?.new_approval_id;
      setSuccessMsg(`Regenerated → new approval ${newId} is PENDING. Refreshing…`);
      setRejected(prev => prev.filter(a => a.id !== approvalId));
      await loadApprovals();
    } catch (e) {
      setError(e.message || 'Regeneration failed — please try again');
    } finally {
      setRegenerating(null);
    }
  };

  return (
    <div className="flex gap-5" style={{ height: 'calc(100vh - 200px)' }}>
      {/* Left: pending list */}
      <div className="w-72 flex-shrink-0 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Clock size={14} className="text-slate-400" />
            <span
              className="font-semibold text-slate-900 text-sm"
              style={{ fontFamily: 'Outfit, sans-serif' }}
            >
              Pending Approvals
            </span>
          </div>
          <div className="flex items-center gap-2">
            {approvals.length > 0 && (
              <Badge variant="warning" dot>{approvals.length}</Badge>
            )}
            <button
              onClick={loadApprovals}
              title="Refresh"
              className="p-1 rounded-lg text-slate-400 hover:text-indigo-600 hover:bg-slate-100 transition-colors"
            >
              <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        <div className="overflow-y-auto flex-1">
          {loading ? (
            <div className="flex justify-center py-8">
              <Loader2 size={20} className="animate-spin text-slate-300" />
            </div>
          ) : approvals.length === 0 ? (
            <div className="px-4 py-8 text-center">
              <CheckCircle size={28} className="text-slate-200 mx-auto mb-2" />
              <p className="text-sm text-slate-400">No pending approvals</p>
            </div>
          ) : (
            approvals.map(approval => (
              <button
                key={approval.id}
                onClick={() => loadDocument(approval.id)}
                className={`w-full text-left px-4 py-3 border-b border-slate-100 last:border-0 hover:bg-slate-50 transition-colors flex items-center justify-between gap-2 ${
                  selectedId === approval.id
                    ? 'bg-indigo-50 border-l-2 border-l-indigo-500 pl-3.5'
                    : ''
                }`}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900 truncate">
                    {approval.name || approval.id}
                  </p>
                  <p className="text-xs font-mono text-slate-400 mt-0.5 truncate">{approval.id}</p>
                  {approval.type && (
                    <span className="inline-block mt-1 px-2 py-0.5 bg-slate-100 text-slate-600 rounded-full text-xs">
                      {approval.type}
                    </span>
                  )}
                </div>
                <ChevronRight size={13} className="text-slate-400 flex-shrink-0" />
              </button>
            ))
          )}
        </div>

        {/* Rejected — available for regeneration */}
        {rejected.length > 0 && (
          <div className="mt-3 border-t border-slate-200 pt-3">
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 px-1">
              Rejected ({rejected.length})
            </p>
            <div className="space-y-1.5">
              {rejected.map(a => (
                <div
                  key={a.id}
                  className="p-2.5 rounded-lg bg-rose-50 border border-rose-100"
                >
                  <p className="text-xs font-medium text-slate-700 truncate mb-1.5">
                    {a.name || a.id}
                  </p>
                  <button
                    onClick={() => handleRegenerate(a.id)}
                    disabled={regenerating === a.id}
                    className="w-full py-1 bg-rose-600 text-white rounded text-xs font-semibold
                               hover:bg-rose-700 disabled:opacity-50 transition-colors"
                  >
                    {regenerating === a.id ? 'Regenerating…' : 'Regenerate with Feedback'}
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Right: review panel */}
      <div className="flex-1 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden flex flex-col">
        {/* Banner messages */}
        {successMsg && (
          <div className="flex items-center gap-2 text-emerald-700 bg-emerald-50 border-b border-emerald-200 px-5 py-3 text-sm font-medium flex-shrink-0">
            <CheckCircle size={15} /> {successMsg}
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border-b border-rose-200 px-5 py-3 text-sm flex-shrink-0">
            <AlertCircle size={15} /> {error}
          </div>
        )}

        {!selectedId ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-8">
            <Clock size={40} className="text-slate-200 mb-3" />
            <p
              className="font-semibold text-slate-500"
              style={{ fontFamily: 'Outfit, sans-serif' }}
            >
              Select a document to review
            </p>
            <p className="text-slate-400 text-sm mt-1">
              Click a pending approval from the list on the left
            </p>
          </div>
        ) : (
          <>
            {/* Editor header */}
            <div className="px-5 py-2.5 border-b border-slate-100 bg-slate-50 flex items-center gap-2 flex-shrink-0">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                Document Content
              </span>
              <span className="text-xs text-slate-400">(editable before approval)</span>
            </div>

            {/* Textarea */}
            <textarea
              value={content}
              onChange={e => setContent(e.target.value)}
              className="flex-1 resize-none p-5 text-sm font-mono text-slate-700 outline-none border-0 focus:ring-0"
              placeholder="Document content will appear here…"
              spellCheck={false}
            />

            {/* Action bar */}
            <div className="px-5 py-4 border-t border-slate-200 bg-slate-50 flex-shrink-0">
              {rejectMode ? (
                <div className="space-y-3">
                  <textarea
                    value={feedback}
                    onChange={e => setFeedback(e.target.value)}
                    placeholder="Explain what needs to be improved (required)…"
                    rows={3}
                    className="w-full text-sm p-3 border border-slate-300 rounded-xl outline-none focus:border-rose-400 focus:ring-1 focus:ring-rose-100 resize-none"
                  />
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleReject}
                      disabled={submitting || !feedback.trim()}
                      className="flex items-center gap-2 px-4 py-2 bg-rose-600 text-white rounded-xl text-sm font-semibold hover:bg-rose-700 disabled:opacity-50 transition-colors"
                    >
                      {submitting
                        ? <Loader2 size={13} className="animate-spin" />
                        : <XCircle size={13} />
                      }
                      Submit Rejection
                    </button>
                    <button
                      onClick={() => { setRejectMode(false); setError(null); }}
                      className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <button
                    onClick={handleApprove}
                    disabled={submitting || !content.trim()}
                    className="flex items-center gap-2 px-5 py-2.5 bg-emerald-600 text-white rounded-xl text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50 transition-colors"
                  >
                    {submitting
                      ? <Loader2 size={13} className="animate-spin" />
                      : <CheckCircle size={13} />
                    }
                    Approve &amp; Stage
                  </button>
                  <button
                    onClick={() => setRejectMode(true)}
                    className="flex items-center gap-2 px-5 py-2.5 bg-white border border-rose-300 text-rose-700 rounded-xl text-sm font-semibold hover:bg-rose-50 transition-colors"
                  >
                    <XCircle size={13} />
                    Reject &amp; Retry
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
