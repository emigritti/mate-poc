import { useState, useEffect } from 'react';
import {
  Clock, CheckCircle, XCircle, Loader2, Sparkles, BookOpen,
  ChevronDown, ChevronRight, ThumbsUp, ThumbsDown, AlertCircle,
  RotateCcw, Eye, Code2,
} from 'lucide-react';
import MarkdownViewer from '../ui/MarkdownViewer.jsx';
import GenerationReportPanel from '../ui/GenerationReportPanel.jsx';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '../ui/sheet.jsx';
import { API } from '../../api.js';

// ── Markdown helpers ──────────────────────────────────────────────────────────

function parseDocBlocks(markdown) {
  const lines = (markdown ?? '').split('\n');
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
  if (preamble.length > 0 && current === null) blocks.push({ title: null, content: preamble.join('\n') });
  if (current !== null) blocks.push({ ...current, content: current.lines.join('\n') });
  return blocks;
}

function reconstructDoc(blocks) {
  return blocks.map(b => b.content).join('\n');
}

// ── Type pills ────────────────────────────────────────────────────────────────

const TYPE_PILL = {
  'REST-to-REST': 'bg-sky-100 text-sky-700',
  'REST-to-SOAP': 'bg-purple-100 text-purple-700',
  'SOAP-to-REST': 'bg-violet-100 text-violet-700',
  'File-based':   'bg-amber-100 text-amber-700',
};

// ── ReviewPanel ───────────────────────────────────────────────────────────────

export default function ReviewPanel({
  approval, content, onContentChange,
  onApprove, onReject,
  isApproving, isRejecting,
}) {
  const [viewMode,         setViewMode]         = useState('rendered'); // 'rendered' | 'raw'
  const [blocks,           setBlocks]           = useState([]);
  const [expandedIdx,      setExpandedIdx]      = useState(null);
  const [sectionEdit,      setSectionEdit]      = useState('');
  const [sectionOriginal,  setSectionOriginal]  = useState('');
  const [sectionsOpen,     setSectionsOpen]     = useState(true);
  const [rejectMode,       setRejectMode]       = useState(false);
  const [feedback,         setFeedback]         = useState('');

  // AI improvement Sheet
  const [aiOpen,    setAiOpen]    = useState(false);
  const [aiPhase,   setAiPhase]   = useState('prompt'); // 'prompt' | 'suggestion'
  const [aiPrompt,  setAiPrompt]  = useState('');
  const [aiSuggest, setAiSuggest] = useState('');
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError,   setAiError]   = useState(null);

  // Reset all local state when a new approval is selected
  useEffect(() => {
    if (!approval) return;
    setBlocks(parseDocBlocks(content));
    setExpandedIdx(null);
    setRejectMode(false);
    setFeedback('');
    setViewMode('rendered');
    setAiOpen(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [approval?.id]);

  // Keep blocks in sync when content changes externally (raw edit)
  useEffect(() => {
    if (expandedIdx === null) {
      setBlocks(parseDocBlocks(content));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content]);

  // ── Section edit helpers ───────────────────────────────────────────────────

  const toggleSection = (idx) => {
    if (expandedIdx === idx) { setExpandedIdx(null); return; }
    setExpandedIdx(idx);
    setSectionEdit(blocks[idx].content);
    setSectionOriginal(blocks[idx].content);
  };

  const saveSection = () => {
    if (expandedIdx === null) return;
    const newBlocks = blocks.map((b, i) =>
      i === expandedIdx ? { ...b, content: sectionEdit } : b
    );
    setBlocks(newBlocks);
    onContentChange(reconstructDoc(newBlocks));
    setExpandedIdx(null);
  };

  // ── AI improvement helpers ─────────────────────────────────────────────────

  const openAiSheet = async () => {
    if (expandedIdx === null) return;
    const block = blocks[expandedIdx];
    setAiPhase('prompt');
    setAiSuggest('');
    setAiError(null);
    setAiLoading(true);
    setAiOpen(true);
    try {
      const res  = await API.approvals.buildImprovementPrompt(block.title, sectionEdit);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || 'Failed to build prompt');
      setAiPrompt(json.data.prompt);
    } catch (e) {
      setAiError(e.message);
    } finally {
      setAiLoading(false);
    }
  };

  const runImprovement = async () => {
    if (expandedIdx === null) return;
    const block = blocks[expandedIdx];
    setAiLoading(true);
    setAiError(null);
    try {
      const res  = await API.approvals.runImprovement(block.title, sectionEdit, aiPrompt);
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail || 'LLM call failed');
      setAiSuggest(json.data.suggested_content);
      setAiPhase('suggestion');
    } catch (e) {
      setAiError(e.message);
    } finally {
      setAiLoading(false);
    }
  };

  const acceptSuggestion = () => {
    setSectionEdit(aiSuggest);
    const newBlocks = blocks.map((b, i) =>
      i === expandedIdx ? { ...b, content: aiSuggest } : b
    );
    setBlocks(newBlocks);
    onContentChange(reconstructDoc(newBlocks));
    setAiOpen(false);
    setAiPhase('prompt');
    setAiSuggest('');
  };

  // ── Derived ───────────────────────────────────────────────────────────────

  const namedSections  = blocks.map((b, idx) => ({ ...b, idx })).filter(b => b.title !== null);
  const submitting     = isApproving || isRejecting;
  const currentBlock   = expandedIdx !== null ? blocks[expandedIdx] : null;
  const typeCls        = TYPE_PILL[approval?.type] ?? 'bg-zinc-100 text-zinc-600';

  // ── Empty state ───────────────────────────────────────────────────────────

  if (!approval) {
    return (
      <div className="flex-1 bg-white rounded-xl border border-zinc-200 flex flex-col items-center justify-center text-center px-8">
        <Clock size={40} className="text-zinc-200 mb-3" />
        <p className="font-semibold text-zinc-500" style={{ fontFamily: 'Outfit, sans-serif' }}>
          Select a document to review
        </p>
        <p className="text-zinc-400 text-sm mt-1">
          Click a pending approval from the queue on the left
        </p>
      </div>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="flex-1 bg-white rounded-xl border border-zinc-200 overflow-hidden flex flex-col min-w-0">

      {/* ── Document header ──────────────────────────────────────────────── */}
      <div className="px-5 py-4 border-b border-zinc-100 flex items-start justify-between gap-4 flex-shrink-0">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h2
              className="text-base font-semibold text-zinc-900 leading-tight"
              style={{ fontFamily: 'Outfit, sans-serif' }}
            >
              {approval.name || approval.id}
            </h2>
            {approval.type && (
              <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${typeCls}`}>
                {approval.type}
              </span>
            )}
          </div>
          <p className="text-zinc-400 text-xs font-mono mt-0.5">{approval.id}</p>
        </div>

        {/* Preview / Raw toggle */}
        <div className="flex gap-0.5 bg-zinc-100 rounded-lg p-0.5 border border-zinc-200 flex-shrink-0">
          <button
            onClick={() => setViewMode('rendered')}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
              viewMode === 'rendered' ? 'bg-white text-zinc-900 shadow-sm' : 'text-zinc-500 hover:text-zinc-700'
            }`}
          >
            <Eye size={11} /> Preview
          </button>
          <button
            onClick={() => setViewMode('raw')}
            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
              viewMode === 'raw' ? 'bg-white text-zinc-900 shadow-sm' : 'text-zinc-500 hover:text-zinc-700'
            }`}
          >
            <Code2 size={11} /> Raw
          </button>
        </div>
      </div>

      {/* ── Action bar ───────────────────────────────────────────────────── */}
      <div className="px-5 py-3 border-b border-zinc-100 bg-zinc-50 flex-shrink-0">
        {rejectMode ? (
          <div className="flex items-center gap-2">
            <textarea
              value={feedback}
              onChange={e => setFeedback(e.target.value)}
              placeholder="Explain what needs improvement (required)…"
              rows={1}
              className="flex-1 text-sm px-3 py-2 border border-zinc-200 rounded-lg outline-none focus:border-rose-400 resize-none"
            />
            <button
              onClick={() => onReject({ id: approval.id, feedback })}
              disabled={submitting || !feedback.trim()}
              className="flex items-center gap-1.5 px-4 py-2 bg-rose-600 text-white rounded-lg text-sm font-semibold hover:bg-rose-700 disabled:opacity-50 transition-colors flex-shrink-0"
            >
              {isRejecting
                ? <Loader2 size={13} className="animate-spin" />
                : <XCircle size={13} />
              }
              Submit Rejection
            </button>
            <button
              onClick={() => { setRejectMode(false); setFeedback(''); }}
              className="text-zinc-400 hover:text-zinc-600 transition-colors text-sm px-2 flex-shrink-0"
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button
              onClick={() => onApprove({ id: approval.id, content })}
              disabled={submitting || !content.trim()}
              className="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-semibold hover:bg-emerald-700 disabled:opacity-50 transition-colors"
            >
              {isApproving
                ? <Loader2 size={13} className="animate-spin" />
                : <CheckCircle size={13} />
              }
              Approve &amp; Stage
            </button>
            <button
              onClick={() => setRejectMode(true)}
              disabled={submitting}
              className="flex items-center gap-1.5 px-4 py-2 bg-white border border-rose-300 text-rose-700 rounded-lg text-sm font-semibold hover:bg-rose-50 disabled:opacity-50 transition-colors"
            >
              <XCircle size={13} />
              Reject
            </button>
          </div>
        )}
      </div>

      {/* ── RAG generation report (collapsible) ──────────────────────────── */}
      <GenerationReportPanel report={approval.generation_report} />

      {/* ── Content area ─────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto min-h-0">
        {viewMode === 'rendered' ? (
          <div className="p-5">
            <MarkdownViewer>{content}</MarkdownViewer>
          </div>
        ) : (
          <textarea
            value={content}
            onChange={e => onContentChange(e.target.value)}
            className="w-full h-full resize-none p-5 text-sm font-mono text-zinc-700 outline-none border-0 focus:ring-0"
            spellCheck={false}
            placeholder="Document content will appear here…"
          />
        )}
      </div>

      {/* ── Section editing panel ─────────────────────────────────────────── */}
      {namedSections.length > 0 && (
        <div className="border-t border-zinc-200 flex-shrink-0" style={{ maxHeight: '45%' }}>
          {/* Panel header / toggle */}
          <button
            onClick={() => setSectionsOpen(o => !o)}
            className="w-full flex items-center gap-2 px-5 py-3 text-sm text-zinc-600 hover:bg-zinc-50 transition-colors"
          >
            {sectionsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <BookOpen size={13} className="text-zinc-400" />
            <span className="font-medium">Edit Sections</span>
            <span className="text-zinc-400 text-xs ml-1">({namedSections.length})</span>
          </button>

          {sectionsOpen && (
            <div className="overflow-y-auto border-t border-zinc-100" style={{ maxHeight: 'calc(45vh - 48px)' }}>
              {namedSections.map(({ idx, title }) => {
                const isExpanded = expandedIdx === idx;
                return (
                  <div key={idx} className="border-b border-zinc-100 last:border-0">
                    {/* Section row */}
                    <button
                      onClick={() => toggleSection(idx)}
                      className={`w-full flex items-center gap-2 px-5 py-2.5 text-left transition-colors ${
                        isExpanded ? 'bg-sky-50' : 'hover:bg-zinc-50'
                      }`}
                    >
                      {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      <span className={`text-sm truncate ${isExpanded ? 'text-sky-700 font-medium' : 'text-zinc-700'}`}>
                        {title}
                      </span>
                    </button>

                    {/* Inline editor */}
                    {isExpanded && (
                      <div className="px-5 pb-4 bg-sky-50/40">
                        <textarea
                          value={sectionEdit}
                          onChange={e => setSectionEdit(e.target.value)}
                          rows={7}
                          className="w-full text-sm font-mono text-zinc-700 border border-zinc-200 rounded-lg p-3 outline-none focus:border-sky-400 resize-y bg-white"
                          spellCheck={false}
                        />
                        <div className="flex items-center gap-2 mt-2 flex-wrap">
                          <button
                            onClick={saveSection}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-sky-600 text-white rounded-lg text-xs font-semibold hover:bg-sky-700 transition-colors"
                          >
                            <CheckCircle size={12} />
                            Save Section
                          </button>
                          <button
                            onClick={openAiSheet}
                            disabled={aiLoading || !sectionEdit.trim()}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-violet-300 text-violet-700 rounded-lg text-xs font-semibold hover:bg-violet-50 disabled:opacity-50 transition-colors"
                          >
                            {aiLoading
                              ? <Loader2 size={12} className="animate-spin" />
                              : <Sparkles size={12} />
                            }
                            {aiLoading ? 'Analyzing…' : 'Improve with AI'}
                          </button>
                          <button
                            onClick={() => setSectionEdit(sectionOriginal)}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-zinc-200 text-zinc-600 rounded-lg text-xs font-semibold hover:bg-zinc-50 transition-colors"
                          >
                            <RotateCcw size={12} />
                            Reset
                          </button>
                          <button
                            onClick={() => setExpandedIdx(null)}
                            className="text-zinc-400 hover:text-zinc-600 transition-colors text-xs px-2"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── AI Improvement Sheet ──────────────────────────────────────────── */}
      <Sheet open={aiOpen} onOpenChange={(open) => { if (!open) { setAiOpen(false); setAiPhase('prompt'); setAiSuggest(''); setAiError(null); } }}>
        <SheetContent className="w-[480px] sm:w-[520px] flex flex-col">
          <SheetHeader className="flex-shrink-0">
            <SheetTitle className="flex items-center gap-2">
              <Sparkles size={15} className="text-violet-500" />
              {aiPhase === 'suggestion' ? 'AI Suggestion' : 'Improvement Prompt'}
            </SheetTitle>
            {currentBlock?.title && (
              <p className="text-zinc-400 text-xs font-mono mt-1 truncate">{currentBlock.title}</p>
            )}
          </SheetHeader>

          <div className="flex-1 flex flex-col mt-6 min-h-0 gap-4">
            {aiError && (
              <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2 text-xs flex-shrink-0">
                <AlertCircle size={12} /> {aiError}
              </div>
            )}

            {aiPhase === 'prompt' ? (
              <>
                <p className="text-zinc-500 text-xs flex-shrink-0">
                  Review and edit the improvement prompt before sending it to the LLM.
                </p>
                {aiLoading && !aiPrompt ? (
                  <div className="flex items-center gap-2 text-zinc-400 text-sm">
                    <Loader2 size={14} className="animate-spin" /> Building prompt…
                  </div>
                ) : (
                  <textarea
                    value={aiPrompt}
                    onChange={e => setAiPrompt(e.target.value)}
                    className="flex-1 resize-none text-sm font-mono text-zinc-700 border border-zinc-200 rounded-lg p-3 outline-none focus:border-violet-400 min-h-0"
                    spellCheck={false}
                  />
                )}
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    onClick={runImprovement}
                    disabled={aiLoading || !aiPrompt.trim()}
                    className="flex items-center gap-1.5 px-4 py-2 bg-violet-600 text-white rounded-lg text-sm font-semibold hover:bg-violet-700 disabled:opacity-50 transition-colors"
                  >
                    {aiLoading
                      ? <Loader2 size={13} className="animate-spin" />
                      : <Sparkles size={13} />
                    }
                    {aiLoading ? 'Generating…' : 'Generate Suggestion'}
                  </button>
                </div>
              </>
            ) : (
              <>
                <p className="text-zinc-500 text-xs flex-shrink-0">
                  Accept to apply this suggestion to the section editor, or revise the prompt and try again.
                </p>
                <textarea
                  value={aiSuggest}
                  readOnly
                  className="flex-1 resize-none text-sm font-mono text-zinc-700 bg-violet-50 border border-violet-200 rounded-lg p-3 outline-none min-h-0"
                  spellCheck={false}
                />
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    onClick={acceptSuggestion}
                    className="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-semibold hover:bg-emerald-700 transition-colors"
                  >
                    <ThumbsUp size={13} /> Accept
                  </button>
                  <button
                    onClick={() => { setAiPhase('prompt'); setAiSuggest(''); setAiError(null); }}
                    className="flex items-center gap-1.5 px-4 py-2 bg-white border border-zinc-200 text-zinc-600 rounded-lg text-sm font-semibold hover:bg-zinc-50 transition-colors"
                  >
                    <ThumbsDown size={13} /> Revise Prompt
                  </button>
                </div>
              </>
            )}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
