import { useState } from 'react';
import {
  CheckCircle, XCircle, AlertCircle, Loader2, Clock, ChevronRight, RefreshCw,
  BookOpen, X, RotateCcw, Sparkles, ChevronLeft, ThumbsUp, ThumbsDown,
} from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import GenerationReportPanel from '../ui/GenerationReportPanel.jsx';
import { useApprovals } from '../../hooks/useApprovals';
import { useQueryClient } from '@tanstack/react-query';
import { API } from '../../api.js';

/** Parse markdown into blocks preserving structure.
 *  Returns array of { title: string|null, content: string }
 *  title===null means preamble (text before first heading). */
function parseDocBlocks(markdown) {
  const lines = markdown.split('\n');
  const blocks = [];
  let current = null;
  const preamble = [];

  for (const line of lines) {
    const match = line.match(/^(#{1,6})\s+(.+)/);
    if (match) {
      if (current === null && preamble.length > 0) {
        blocks.push({ title: null, content: preamble.join('\n') });
        preamble.length = 0;
      } else if (current !== null) {
        blocks.push({ ...current, content: current.lines.join('\n') });
      }
      current = { title: match[2].trim(), lines: [line] };
    } else {
      if (current !== null) current.lines.push(line);
      else preamble.push(line);
    }
  }
  if (preamble.length > 0 && current === null) {
    blocks.push({ title: null, content: preamble.join('\n') });
  }
  if (current !== null) {
    blocks.push({ ...current, content: current.lines.join('\n') });
  }
  return blocks;
}

function reconstructDoc(blocks) {
  return blocks.map(b => b.content).join('\n');
}

// ── Section modal phase labels ────────────────────────────────────────────────
// 'edit'       — section editor (default)
// 'prompt'     — AI improvement prompt preview/edit (phase 1)
// 'suggestion' — LLM suggestion review (phase 2)

export default function ApprovalsPage() {
  const {
    approvals,
    isLoading,
    loadError,
    approve,
    isApproving,
    reject,
    isRejecting,
    regenerate,
    isRegenerating,
  } = useApprovals();
  const queryClient = useQueryClient();

  const [selectedId, setSelectedId] = useState(null);
  const [content, setContent]       = useState('');
  const [feedback, setFeedback]     = useState('');
  const [rejectMode, setRejectMode] = useState(false);
  const [error, setError]           = useState(null);
  const [successMsg, setSuccessMsg] = useState(null);
  const [rejected, setRejected]     = useState([]);

  // Section modal state
  const [sectionModalOpen, setSectionModalOpen] = useState(false);
  const [sectionBlocks, setSectionBlocks]       = useState([]);
  const [selectedSection, setSelectedSection]   = useState(null);
  const [sectionEdit, setSectionEdit]           = useState('');
  const [sectionOriginal, setSectionOriginal]   = useState('');

  // AI improvement state (phases)
  const [modalPhase, setModalPhase]         = useState('edit');   // 'edit' | 'prompt' | 'suggestion'
  const [improvementPrompt, setImprovementPrompt] = useState('');
  const [suggestion, setSuggestion]         = useState('');
  const [aiLoading, setAiLoading]           = useState(false);
  const [aiError, setAiError]               = useState(null);

  const loadDocument = (id) => {
    setSelectedId(id);
    setRejectMode(false);
    setFeedback('');
    setError(null);
    setSuccessMsg(null);
    const approval = approvals.find(a => a.id === id);
    setContent(approval?.content ?? approval?.document ?? '');
  };

  const handleApprove = () => {
    if (!selectedId) return;
    approve(
      { id: selectedId, content },
      {
        onSuccess: () => {
          setSuccessMsg('Document staged. Use the Documents page to promote to Knowledge Base.');
          setSelectedId(null);
          setContent('');
        },
        onError: (err) => setError(err.message || 'Approval failed — please try again'),
      }
    );
  };

  const handleReject = () => {
    if (!feedback.trim()) {
      setError('Please provide rejection feedback before submitting');
      return;
    }
    reject(
      { id: selectedId, feedback },
      {
        onSuccess: () => {
          setRejected(prev => [
            ...prev,
            { ...approvals.find(a => a.id === selectedId), feedback },
          ]);
          setSuccessMsg('Document rejected — use "Regenerate with Feedback" to retry.');
          setSelectedId(null);
          setRejectMode(false);
          setFeedback('');
        },
        onError: (err) => setError(err.message || 'Rejection failed — please try again'),
      }
    );
  };

  const handleRegenerate = (approvalId) => {
    setError(null);
    setSuccessMsg(null);
    regenerate(
      { id: approvalId },
      {
        onSuccess: (data) => {
          const newId = data.data?.new_approval_id;
          setSuccessMsg(`Regenerated → new approval ${newId} is PENDING.`);
          setRejected(prev => prev.filter(a => a.id !== approvalId));
        },
        onError: (e) => setError(e.message || 'Regeneration failed'),
      }
    );
  };

  // ── Section modal helpers ──────────────────────────────────────────────────

  const openSectionModal = () => {
    const blocks = parseDocBlocks(content);
    setSectionBlocks(blocks);
    const firstIdx = blocks.findIndex(b => b.title !== null);
    if (firstIdx === -1) return;
    setSelectedSection(firstIdx);
    setSectionEdit(blocks[firstIdx].content);
    setSectionOriginal(blocks[firstIdx].content);
    setModalPhase('edit');
    setImprovementPrompt('');
    setSuggestion('');
    setAiError(null);
    setSectionModalOpen(true);
  };

  const handleSectionSelect = (idx) => {
    setSelectedSection(idx);
    setSectionEdit(sectionBlocks[idx].content);
    setSectionOriginal(sectionBlocks[idx].content);
    setModalPhase('edit');
    setImprovementPrompt('');
    setSuggestion('');
    setAiError(null);
  };

  const handleSectionSave = () => {
    if (selectedSection === null) return;
    const newBlocks = sectionBlocks.map((b, i) =>
      i === selectedSection ? { ...b, content: sectionEdit } : b
    );
    setContent(reconstructDoc(newBlocks));
    setSectionModalOpen(false);
  };

  const handleSectionReset = () => {
    setSectionEdit(sectionOriginal);
  };

  // ── ADR-040 AI improvement ─────────────────────────────────────────────────

  const handleRequestPrompt = async () => {
    if (selectedSection === null) return;
    const block = sectionBlocks[selectedSection];
    setAiLoading(true);
    setAiError(null);
    try {
      const res = await API.approvals.buildImprovementPrompt(block.title, sectionEdit);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || 'Failed to build prompt');
      setImprovementPrompt(json.data.prompt);
      setModalPhase('prompt');
    } catch (e) {
      setAiError(e.message);
    } finally {
      setAiLoading(false);
    }
  };

  const handleRunImprovement = async () => {
    if (selectedSection === null) return;
    const block = sectionBlocks[selectedSection];
    setAiLoading(true);
    setAiError(null);
    try {
      const res = await API.approvals.runImprovement(block.title, sectionEdit, improvementPrompt);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || 'LLM call failed');
      setSuggestion(json.data.suggested_content);
      setModalPhase('suggestion');
    } catch (e) {
      setAiError(e.message);
    } finally {
      setAiLoading(false);
    }
  };

  const handleAcceptSuggestion = () => {
    setSectionEdit(suggestion);
    // Sync the update into sectionBlocks so Save reflects it
    setSectionBlocks(prev =>
      prev.map((b, i) => i === selectedSection ? { ...b, content: suggestion } : b)
    );
    setModalPhase('edit');
    setSuggestion('');
  };

  const handleRejectSuggestion = () => {
    setModalPhase('prompt');
    setSuggestion('');
  };

  const closeModal = () => {
    setSectionModalOpen(false);
    setModalPhase('edit');
    setImprovementPrompt('');
    setSuggestion('');
    setAiError(null);
  };

  const submitting = isApproving || isRejecting;

  // ── Modal phase-specific content ───────────────────────────────────────────

  const renderModalBody = () => {
    if (modalPhase === 'prompt') {
      return (
        <>
          {aiError && (
            <div className="mx-6 mt-3 flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 text-xs flex-shrink-0">
              <AlertCircle size={12} /> {aiError}
            </div>
          )}
          <div className="px-6 pt-4 pb-1 flex-shrink-0">
            <p className="text-xs text-slate-500">
              Review and edit the improvement prompt before sending it to the LLM.
            </p>
          </div>
          <textarea
            value={improvementPrompt}
            onChange={e => setImprovementPrompt(e.target.value)}
            className="flex-1 resize-none px-6 py-3 text-sm font-mono text-slate-700 outline-none border-0 focus:ring-0 min-h-0"
            spellCheck={false}
          />
          <div className="px-6 py-4 border-t border-slate-100 bg-slate-50 flex items-center gap-2 flex-shrink-0 rounded-b-2xl">
            <button
              onClick={handleRunImprovement}
              disabled={aiLoading || !improvementPrompt.trim()}
              className="flex items-center gap-2 px-4 py-2 bg-violet-600 text-white rounded-xl text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 transition-colors"
            >
              {aiLoading
                ? <Loader2 size={13} className="animate-spin" />
                : <Sparkles size={13} />
              }
              {aiLoading ? 'Generating…' : 'Generate'}
            </button>
            <button
              onClick={() => { setModalPhase('edit'); setAiError(null); }}
              className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-600 rounded-xl text-sm font-semibold hover:bg-slate-100 transition-colors"
            >
              <ChevronLeft size={13} />
              Back
            </button>
          </div>
        </>
      );
    }

    if (modalPhase === 'suggestion') {
      return (
        <>
          {aiError && (
            <div className="mx-6 mt-3 flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 text-xs flex-shrink-0">
              <AlertCircle size={12} /> {aiError}
            </div>
          )}
          <div className="px-6 pt-4 pb-1 flex-shrink-0">
            <p className="text-xs text-slate-500">
              AI suggestion — accept to overwrite the section, or go back to edit the prompt.
            </p>
          </div>
          <textarea
            value={suggestion}
            readOnly
            className="flex-1 resize-none px-6 py-3 text-sm font-mono text-slate-700 bg-violet-50 outline-none border-0 focus:ring-0 min-h-0"
            spellCheck={false}
          />
          <div className="px-6 py-4 border-t border-slate-100 bg-slate-50 flex items-center gap-2 flex-shrink-0 rounded-b-2xl">
            <button
              onClick={handleAcceptSuggestion}
              className="flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-xl text-sm font-semibold hover:bg-emerald-700 transition-colors"
            >
              <ThumbsUp size={13} />
              Accept
            </button>
            <button
              onClick={handleRejectSuggestion}
              className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-600 rounded-xl text-sm font-semibold hover:bg-slate-100 transition-colors"
            >
              <ThumbsDown size={13} />
              Back to Prompt
            </button>
          </div>
        </>
      );
    }

    // default: 'edit'
    return (
      <>
        {aiError && (
          <div className="mx-6 mt-3 flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 text-xs flex-shrink-0">
            <AlertCircle size={12} /> {aiError}
          </div>
        )}
        <textarea
          value={sectionEdit}
          onChange={e => setSectionEdit(e.target.value)}
          className="flex-1 resize-none px-6 py-4 text-sm font-mono text-slate-700 outline-none border-0 focus:ring-0 min-h-0"
          spellCheck={false}
        />
        <div className="px-6 py-4 border-t border-slate-100 bg-slate-50 flex items-center gap-2 flex-shrink-0 rounded-b-2xl">
          <button
            onClick={handleSectionSave}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-xl text-sm font-semibold hover:bg-indigo-700 transition-colors"
          >
            <CheckCircle size={13} />
            Save
          </button>
          <button
            onClick={handleRequestPrompt}
            disabled={aiLoading || !sectionEdit.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-white border border-violet-300 text-violet-700 rounded-xl text-sm font-semibold hover:bg-violet-50 disabled:opacity-50 transition-colors"
          >
            {aiLoading
              ? <Loader2 size={13} className="animate-spin" />
              : <Sparkles size={13} />
            }
            {aiLoading ? 'Analyzing…' : 'Improve with AI'}
          </button>
          <button
            onClick={handleSectionReset}
            className="flex items-center gap-2 px-4 py-2 bg-white border border-slate-300 text-slate-600 rounded-xl text-sm font-semibold hover:bg-slate-100 transition-colors"
          >
            <RotateCcw size={13} />
            Reset
          </button>
          <button
            onClick={closeModal}
            className="px-4 py-2 text-sm text-slate-500 hover:text-slate-700 transition-colors"
          >
            Cancel
          </button>
        </div>
      </>
    );
  };

  const modalTitle = {
    edit: 'Review Section',
    prompt: 'Improvement Prompt',
    suggestion: 'AI Suggestion',
  }[modalPhase];

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
              onClick={() => queryClient.invalidateQueries({ queryKey: ['approvals', 'pending'] })}
              title="Refresh"
              className="p-1 rounded-lg text-slate-400 hover:text-indigo-600 hover:bg-slate-100 transition-colors"
            >
              <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
            </button>
          </div>
        </div>

        <div className="overflow-y-auto flex-1">
          {isLoading ? (
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
                    disabled={isRegenerating}
                    className="w-full py-1 bg-rose-600 text-white rounded text-xs font-semibold
                               hover:bg-rose-700 disabled:opacity-50 transition-colors"
                  >
                    {isRegenerating ? 'Regenerating…' : 'Regenerate with Feedback'}
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

            {/* Source Report — collapsible traceability panel */}
            <GenerationReportPanel
              report={approvals.find(a => a.id === selectedId)?.generation_report}
            />

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
                    onClick={openSectionModal}
                    disabled={!content.trim()}
                    className="flex items-center gap-2 px-5 py-2.5 bg-white border border-indigo-300 text-indigo-700 rounded-xl text-sm font-semibold hover:bg-indigo-50 disabled:opacity-50 transition-colors"
                  >
                    <BookOpen size={13} />
                    Review Section
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

      {/* Section edit modal */}
      {sectionModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={closeModal}
        >
          <div
            className="bg-white rounded-2xl shadow-xl w-full max-w-2xl mx-4 flex flex-col"
            style={{ maxHeight: '80vh' }}
            onClick={e => e.stopPropagation()}
          >
            {/* Modal header */}
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-2">
                {modalPhase === 'suggestion'
                  ? <Sparkles size={15} className="text-violet-500" />
                  : modalPhase === 'prompt'
                    ? <Sparkles size={15} className="text-violet-400" />
                    : <BookOpen size={15} className="text-indigo-500" />
                }
                <span className="font-semibold text-slate-800 text-sm" style={{ fontFamily: 'Outfit, sans-serif' }}>
                  {modalTitle}
                </span>
                {modalPhase !== 'edit' && (
                  <span className="text-xs text-slate-400 font-mono truncate max-w-[220px]">
                    — {sectionBlocks[selectedSection]?.title}
                  </span>
                )}
              </div>
              <button
                onClick={closeModal}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            {/* Section selector — only in edit phase */}
            {modalPhase === 'edit' && (
              <div className="px-6 py-3 border-b border-slate-100 flex-shrink-0">
                <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider block mb-1.5">
                  Section
                </label>
                <select
                  value={selectedSection ?? ''}
                  onChange={e => handleSectionSelect(Number(e.target.value))}
                  className="w-full text-sm px-3 py-2 border border-slate-300 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 bg-white text-slate-700"
                >
                  {sectionBlocks.map((b, i) =>
                    b.title !== null ? (
                      <option key={i} value={i}>{b.title}</option>
                    ) : null
                  )}
                </select>
              </div>
            )}

            {/* Phase-specific body */}
            {renderModalBody()}
          </div>
        </div>
      )}
    </div>
  );
}
