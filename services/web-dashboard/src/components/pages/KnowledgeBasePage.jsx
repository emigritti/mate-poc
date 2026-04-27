import { useState, useEffect, useRef } from 'react';
import {
    Upload, Tag, FileText, X, Loader2,
    AlertCircle, BookOpen, BarChart3,
    FileSpreadsheet, FileType, Presentation, Link,
    ArrowDownToLine,
} from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';
import TagEditModal from '../kb/TagEditModal';
import PreviewModal from '../kb/PreviewModal';
import SearchPanel from '../kb/SearchPanel';
import UnifiedDocumentsPanel from '../kb/UnifiedDocumentsPanel';
import AddUrlForm from '../kb/AddUrlForm';
import KBExportImportModal from '../kb/KBExportImportModal';

const FILE_TYPE_ICONS = {
    pdf: FileText,
    docx: FileType,
    xlsx: FileSpreadsheet,
    pptx: Presentation,
    md: FileText,
};

const FILE_TYPE_LABELS = {
    pdf: 'PDF',
    docx: 'Word',
    xlsx: 'Excel',
    pptx: 'PowerPoint',
    md: 'Markdown',
};

const ACCEPTED_EXTENSIONS = '.pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.md,.txt,.png,.jpg,.jpeg,.svg';

// ── Unified KB helpers ───────────────────────────────────────────────────────

/**
 * Merge KB-uploaded docs and promoted integration docs into a single array.
 * Only integration docs with kb_status === "promoted" are included.
 */
function normalizeKBDocs(kbList = [], intList = []) {
    const uploaded = kbList.map(d => ({
        id: d.id,
        name: d.filename,
        tags: d.tags || [],
        date: d.uploaded_at,
        source: d.file_type === 'url' ? 'url' : 'uploaded',
        previewText: d.content_preview || '',
        chunkCount: d.chunk_count,
        url: d.url || null,
        _kbDoc: d,             // kept for delete / tag-edit actions
    }));
    const integration = intList
        .filter(d => d.kb_status === 'promoted')
        .map(d => ({
            id: d.id,
            name: `${d.integration_id} · Integration Spec`,
            tags: [],
            date: d.generated_at,
            source: 'integration',
            previewText: typeof d.content === 'string' ? d.content.slice(0, 500) : '',
            chunkCount: null,
            docType: d.doc_type,
        }));
    return [...uploaded, ...integration];
}


// ── Main Page ───────────────────────────────────────────────────────────────

export default function KnowledgeBasePage() {
    const [docs, setDocs] = useState([]);
    const [unifiedDocs, setUnifiedDocs] = useState([]);
    const [stats, setStats] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [dragOver, setDragOver] = useState(false);
    const [error, setError] = useState(null);
    const [editingDoc, setEditingDoc] = useState(null);
    const [previewDoc, setPreviewDoc] = useState(null);
    const [deletingId, setDeletingId] = useState(null);
    const [activeTab, setActiveTab] = useState('file');
    const [showExportImport, setShowExportImport] = useState(false);
    const fileInputRef = useRef(null);

    useEffect(() => { loadData(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const loadData = async () => {
        try {
            const [docsRes, statsRes, intDocsRes] = await Promise.all([
                API.kb.list(),
                API.kb.stats(),
                API.documents.list(),
            ]);
            const docsData = await docsRes.json();
            const kbDocs = docsData.data || [];
            setDocs(kbDocs);

            const statsData = await statsRes.json();
            setStats(statsData);

            // Integration docs: graceful fallback if endpoint fails or returns error.
            // GET /api/v1/documents returns a bare array (response_model=list[Document]),
            // not the {"status","data":[]} envelope used by other endpoints.
            let intDocs = [];
            if (intDocsRes.ok) {
                const intData = await intDocsRes.json();
                intDocs = Array.isArray(intData) ? intData : (intData.data || []);
            }

            setUnifiedDocs(normalizeKBDocs(kbDocs, intDocs));
        } catch (e) {
            setError(`Could not load data: ${e.message}`);
        }
    };

    const handleFile = async (file) => {
        if (!file) return;
        setError(null);
        setUploading(true);
        try {
            const res = await API.kb.upload(file);
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                throw new Error(d.detail || `Upload failed (${res.status})`);
            }
            await loadData();
        } catch (e) {
            setError(e.message);
        } finally {
            setUploading(false);
        }
    };

    const handleDelete = async (id) => {
        if (!confirm('Delete this document from the Knowledge Base?')) return;
        setDeletingId(id);
        try {
            const res = await API.kb.delete(id);
            if (!res.ok) throw new Error('Delete failed');
            await loadData();
        } catch (e) {
            setError(e.message);
        } finally {
            setDeletingId(null);
        }
    };

    const handleDeleteIntegration = async (id) => {
        if (!confirm('Remove this integration document from the Knowledge Base?\nThe document will revert to "staged" status and can be re-promoted later.')) return;
        setDeletingId(id);
        try {
            const res = await API.documents.removeFromKB(id);
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                throw new Error(d.detail || 'Remove from KB failed');
            }
            await loadData();
        } catch (e) {
            setError(e.message);
        } finally {
            setDeletingId(null);
        }
    };

    const handlePreviewUnified = (unifiedDoc) => {
        setPreviewDoc({
            filename: unifiedDoc.name,
            chunk_count: unifiedDoc.chunkCount,
            content_preview: unifiedDoc.previewText,
        });
    };

    return (
        <div className="space-y-6 max-w-5xl">
            {/* Page header with Export/Import button */}
            <div className="flex items-center justify-between">
                <h1 className="text-xl font-bold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                    Knowledge Base
                </h1>
                <button
                    onClick={() => setShowExportImport(true)}
                    className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 hover:border-indigo-300 transition-colors shadow-sm"
                >
                    <ArrowDownToLine size={14} className="text-indigo-500" />
                    Export / Import
                </button>
            </div>

            {/* Stats bar */}
            {stats && stats.total_documents > 0 && (
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    {[
                        { label: 'Documents', value: stats.total_documents, icon: BookOpen },
                        { label: 'Chunks', value: stats.total_chunks, icon: BarChart3 },
                        { label: 'File Types', value: Object.keys(stats.file_types).length, icon: FileText },
                        { label: 'Tags', value: stats.all_tags.length, icon: Tag },
                    ].map(s => (
                        <div key={s.label}
                            className="bg-white rounded-xl border border-slate-200 shadow-sm px-4 py-3 flex items-center gap-3">
                            <div className="w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center flex-shrink-0">
                                <s.icon size={16} className="text-indigo-500" />
                            </div>
                            <div>
                                <p className="text-lg font-bold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>{s.value}</p>
                                <p className="text-xs text-slate-400">{s.label}</p>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Add to KB — tabbed: Upload File / Add URL */}
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                {/* Tab switcher */}
                <div className="flex border-b border-slate-200">
                    {[
                        { id: 'file', label: 'Upload File', icon: Upload },
                        { id: 'url',  label: 'Add URL',     icon: Link   },
                    ].map(tab => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`flex items-center gap-2 px-5 py-3 text-sm font-medium transition-colors border-b-2 -mb-px ${
                                activeTab === tab.id
                                    ? 'border-indigo-500 text-indigo-600'
                                    : 'border-transparent text-slate-500 hover:text-slate-700'
                            }`}
                        >
                            <tab.icon size={14} />
                            {tab.label}
                        </button>
                    ))}
                </div>

                {/* File upload pane */}
                {activeTab === 'file' && (
                    <div
                        onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                        onDragLeave={() => setDragOver(false)}
                        onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
                        onClick={() => fileInputRef.current?.click()}
                        className={`p-10 text-center transition-all cursor-pointer select-none ${dragOver
                            ? 'bg-indigo-50'
                            : 'hover:bg-slate-50/80'
                        }`}
                    >
                        <input
                            ref={fileInputRef}
                            type="file"
                            accept={ACCEPTED_EXTENSIONS}
                            className="hidden"
                            onChange={e => handleFile(e.target.files[0])}
                        />
                        {uploading ? (
                            <div className="flex flex-col items-center gap-3 text-indigo-600">
                                <Loader2 size={32} className="animate-spin" />
                                <p className="font-medium" style={{ fontFamily: 'Outfit, sans-serif' }}>
                                    Uploading, parsing and tagging…
                                </p>
                            </div>
                        ) : (
                            <div className="flex flex-col items-center gap-3">
                                <div className="w-14 h-14 rounded-full bg-indigo-50 border border-indigo-100 flex items-center justify-center">
                                    <Upload size={24} className="text-indigo-500" />
                                </div>
                                <div>
                                    <p className="font-semibold text-slate-700" style={{ fontFamily: 'Outfit, sans-serif' }}>
                                        Drop your best-practice document here
                                    </p>
                                    <p className="text-sm text-slate-400 mt-1">
                                        Supports PDF, Word, Excel, PowerPoint, Markdown
                                    </p>
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* Add URL pane */}
                {activeTab === 'url' && (
                    <div className="p-6">
                        <p className="text-xs text-slate-500 mb-4">
                            Register an HTTP/HTTPS URL (e.g. API docs, integration specs).
                            Its content will be fetched live during document generation
                            for integrations whose tags match.
                        </p>
                        <AddUrlForm
                            onAdded={() => loadData()}
                        />
                    </div>
                )}
            </div>

            {error && (
                <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 text-sm">
                    <AlertCircle size={16} /> {error}
                    <button onClick={() => setError(null)} className="ml-auto hover:text-rose-900">
                        <X size={14} />
                    </button>
                </div>
            )}

            {/* Unified KB documents list */}
            <UnifiedDocumentsPanel
                docs={unifiedDocs}
                onDelete={handleDelete}
                onDeleteIntegration={handleDeleteIntegration}
                deletingId={deletingId}
                onPreview={handlePreviewUnified}
                onEditTags={(kbDoc) => setEditingDoc(kbDoc)}
            />

            {/* Semantic Search */}
            <SearchPanel />

            {/* Modals */}
            {editingDoc && (
                <TagEditModal
                    doc={editingDoc}
                    onClose={() => setEditingDoc(null)}
                    onSaved={() => { setEditingDoc(null); loadData(); }}
                />
            )}
            {previewDoc && (
                <PreviewModal
                    doc={previewDoc}
                    onClose={() => setPreviewDoc(null)}
                />
            )}
            {showExportImport && (
                <KBExportImportModal
                    onClose={() => setShowExportImport(false)}
                    onImportDone={() => { setShowExportImport(false); loadData(); }}
                />
            )}
        </div>
    );
}
