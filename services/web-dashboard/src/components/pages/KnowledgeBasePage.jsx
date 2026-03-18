import { useState, useEffect, useRef } from 'react';
import {
    Upload, Trash2, Search, Tag, FileText, X, Loader2,
    AlertCircle, CheckCircle, Eye, BookOpen, BarChart3,
    FileSpreadsheet, FileType, Presentation, Cpu,
} from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

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

const ACCEPTED_EXTENSIONS = '.pdf,.docx,.doc,.xlsx,.xls,.pptx,.ppt,.md,.txt';

function formatBytes(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1_048_576).toFixed(1)} MB`;
}

function formatDate(iso) {
    try {
        return new Date(iso).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
        });
    } catch {
        return iso;
    }
}


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
        source: 'uploaded',
        previewText: d.content_preview || '',
        chunkCount: d.chunk_count,
        _kbDoc: d,             // kept for delete / tag-edit actions
    }));
    const integration = intList
        .filter(d => d.kb_status === 'promoted')
        .map(d => ({
            id: d.id,
            name: `${d.integration_id} · ${d.doc_type}`,
            tags: [],
            date: d.generated_at,
            source: 'integration',
            previewText: typeof d.content === 'string' ? d.content.slice(0, 500) : '',
            chunkCount: null,
            docType: d.doc_type,
        }));
    return [...uploaded, ...integration];
}

/**
 * Filter unified docs by name or tag (case-insensitive).
 * Empty query returns full list unchanged.
 */
function filterDocs(docs = [], query = '') {
    if (!query.trim()) return docs;
    const q = query.toLowerCase();
    return docs.filter(d =>
        d.name.toLowerCase().includes(q) ||
        d.tags.some(t => t.toLowerCase().includes(q))
    );
}


// ── Tag Edit Modal ──────────────────────────────────────────────────────────

function TagEditModal({ doc, onClose, onSaved }) {
    const [tags, setTags] = useState(doc.tags || []);
    const [custom, setCustom] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState(null);
    const MAX_TAGS = 10;

    const addTag = () => {
        const t = custom.trim();
        if (t && !tags.includes(t) && tags.length < MAX_TAGS) {
            setTags(prev => [...prev, t]);
            setCustom('');
        }
    };

    const removeTag = (tag) => setTags(prev => prev.filter(t => t !== tag));

    const save = async () => {
        if (tags.length === 0) return;
        setSaving(true);
        setError(null);
        try {
            const res = await API.kb.updateTags(doc.id, tags);
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                throw new Error(d.detail || `Server error ${res.status}`);
            }
            onSaved();
        } catch (e) {
            setError(e.message);
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in"
            onClick={onClose}>
            <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 overflow-hidden"
                onClick={e => e.stopPropagation()}>
                <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
                    <div>
                        <h3 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                            Edit Tags
                        </h3>
                        <p className="text-xs text-slate-400 mt-0.5">{doc.filename}</p>
                    </div>
                    <button onClick={onClose} className="p-1 hover:bg-slate-100 rounded-lg transition-colors">
                        <X size={18} className="text-slate-400" />
                    </button>
                </div>

                <div className="px-6 py-5 space-y-4">
                    {error && (
                        <div className="flex items-center gap-2 text-rose-600 text-sm bg-rose-50 px-3 py-2 rounded-lg">
                            <AlertCircle size={14} /> {error}
                        </div>
                    )}

                    <div className="flex flex-wrap gap-2">
                        {tags.map(tag => (
                            <span key={tag}
                                className="inline-flex items-center gap-1 px-3 py-1 bg-indigo-100 text-indigo-700 rounded-full text-xs font-medium">
                                {tag}
                                <button onClick={() => removeTag(tag)} className="hover:text-indigo-900 transition-colors">
                                    <X size={10} />
                                </button>
                            </span>
                        ))}
                        {tags.length === 0 && (
                            <span className="text-xs text-slate-400">No tags — add at least one</span>
                        )}
                    </div>

                    <div className="flex gap-2">
                        <input
                            type="text"
                            placeholder="Add tag…"
                            value={custom}
                            onChange={e => setCustom(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && addTag()}
                            disabled={tags.length >= MAX_TAGS}
                            className="flex-1 text-sm px-3 py-2 border border-slate-300 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100 disabled:opacity-50"
                        />
                        <button
                            onClick={addTag}
                            disabled={!custom.trim() || tags.length >= MAX_TAGS}
                            className="px-4 py-2 rounded-lg bg-slate-100 hover:bg-slate-200 text-slate-600 text-sm disabled:opacity-40 transition-colors"
                        >
                            Add
                        </button>
                    </div>
                </div>

                <div className="px-6 py-4 border-t border-slate-100 flex justify-end gap-2">
                    <button onClick={onClose}
                        className="px-4 py-2 text-sm text-slate-600 hover:bg-slate-100 rounded-lg transition-colors">
                        Cancel
                    </button>
                    <button onClick={save} disabled={tags.length === 0 || saving}
                        className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors">
                        {saving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                        Save Tags
                    </button>
                </div>
            </div>
        </div>
    );
}


// ── Preview Modal ───────────────────────────────────────────────────────────

function PreviewModal({ doc, onClose }) {
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in"
            onClick={onClose}>
            <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl mx-4 max-h-[80vh] overflow-hidden flex flex-col"
                onClick={e => e.stopPropagation()}>
                <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
                    <div>
                        <h3 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                            Content Preview
                        </h3>
                        <p className="text-xs text-slate-400 mt-0.5">
                            {doc.filename}{doc.chunk_count != null ? ` · ${doc.chunk_count} chunks` : ''}
                        </p>
                    </div>
                    <button onClick={onClose} className="p-1 hover:bg-slate-100 rounded-lg transition-colors">
                        <X size={18} className="text-slate-400" />
                    </button>
                </div>
                <div className="px-6 py-5 overflow-y-auto flex-1">
                    <pre className="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed">
                        {doc.content_preview || 'No preview available.'}
                    </pre>
                </div>
            </div>
        </div>
    );
}


// ── Search Panel ────────────────────────────────────────────────────────────

function SearchPanel() {
    const [query, setQuery] = useState('');
    const [results, setResults] = useState(null);
    const [searching, setSearching] = useState(false);
    const [error, setError] = useState(null);

    const doSearch = async () => {
        if (!query.trim()) return;
        setSearching(true);
        setError(null);
        try {
            const res = await API.kb.search(query.trim());
            if (!res.ok) throw new Error('Search failed');
            const data = await res.json();
            setResults(data);
        } catch (e) {
            setError(e.message);
        } finally {
            setSearching(false);
        }
    };

    return (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
                <Search size={15} className="text-slate-400" />
                <h2 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                    Semantic Search
                </h2>
            </div>
            <div className="px-5 py-4 space-y-4">
                <div className="flex gap-2">
                    <input
                        type="text"
                        placeholder="Search best practices…"
                        value={query}
                        onChange={e => setQuery(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && doSearch()}
                        className="flex-1 text-sm px-3 py-2 border border-slate-300 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100"
                    />
                    <button
                        onClick={doSearch}
                        disabled={!query.trim() || searching}
                        className="flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
                    >
                        {searching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                        Search
                    </button>
                </div>

                {error && (
                    <div className="flex items-center gap-2 text-rose-600 text-sm bg-rose-50 px-3 py-2 rounded-lg">
                        <AlertCircle size={14} /> {error}
                    </div>
                )}

                {results && (
                    <div className="space-y-3">
                        <p className="text-xs text-slate-500">
                            {results.total_results} result{results.total_results !== 1 ? 's' : ''} for "{results.query}"
                        </p>
                        {results.results.map((r, i) => (
                            <div key={i} className="border border-slate-200 rounded-xl p-4 space-y-2 hover:border-indigo-200 transition-colors">
                                <div className="flex items-center justify-between">
                                    <span className="text-xs font-medium text-slate-500">{r.filename}</span>
                                    {r.score != null && (
                                        <Badge variant={r.score > 0.5 ? 'success' : 'slate'}>
                                            {(r.score * 100).toFixed(0)}% match
                                        </Badge>
                                    )}
                                </div>
                                <p className="text-sm text-slate-700 line-clamp-3">{r.chunk_text}</p>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}


// ── Unified Documents Panel ──────────────────────────────────────────────────

/**
 * Shows all KB documents (uploaded + promoted integration specs) in one table.
 * Includes a client-side text search box that filters by name or tag.
 * Delete action is available only for uploaded docs.
 */
function UnifiedDocumentsPanel({ docs, onDelete, deletingId, onPreview, onEditTags }) {
    const [query, setQuery] = useState('');
    const [displayed, setDisplayed] = useState(docs);
    const timerRef = useRef(null);

    useEffect(() => {
        clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => {
            setDisplayed(filterDocs(docs, query));
        }, 200);
        return () => clearTimeout(timerRef.current);
    }, [query, docs]);

    return (
        <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
            {/* Header */}
            <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
                <BookOpen size={15} className="text-slate-400" />
                <h2 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                    Tutti i Documenti KB
                </h2>
                <Badge variant="slate">{docs.length}</Badge>
            </div>

            {/* Search box */}
            <div className="px-5 py-3 border-b border-slate-100">
                <div className="relative">
                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                    <input
                        type="text"
                        placeholder="Cerca per nome o tag…"
                        value={query}
                        onChange={e => setQuery(e.target.value)}
                        className="w-full pl-9 pr-4 py-2 text-sm border border-slate-200 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100"
                    />
                </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
                <table className="w-full text-sm">
                    <thead className="bg-slate-50">
                        <tr>
                            {['Nome', 'Tipo', 'Tag', 'Data', 'Azioni'].map(h => (
                                <th key={h}
                                    className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                                    {h}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                        {displayed.length === 0 && (
                            <tr>
                                <td colSpan={5} className="px-4 py-8 text-center text-sm text-slate-400">
                                    {query.trim()
                                        ? 'Nessun documento corrisponde alla ricerca.'
                                        : 'Nessun documento presente in KB.'}
                                </td>
                            </tr>
                        )}
                        {displayed.map(doc => (
                            <tr key={doc.id} className="hover:bg-slate-50/70 transition-colors">
                                {/* Nome */}
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-2">
                                        {doc.source === 'uploaded'
                                            ? <FileText size={15} className="text-slate-400 flex-shrink-0" />
                                            : <Cpu size={15} className="text-blue-400 flex-shrink-0" />
                                        }
                                        <p className="font-medium text-slate-900 max-w-[220px] truncate" title={doc.name}>
                                            {doc.name}
                                        </p>
                                    </div>
                                </td>

                                {/* Tipo */}
                                <td className="px-4 py-3">
                                    {doc.source === 'uploaded'
                                        ? <Badge variant="slate">📤 Caricato</Badge>
                                        : <Badge variant="info">⚙️ Integrazione</Badge>
                                    }
                                </td>

                                {/* Tag */}
                                <td className="px-4 py-3">
                                    <div className="flex flex-wrap gap-1 max-w-[180px]">
                                        {doc.tags.length > 0
                                            ? doc.tags.map(tag => (
                                                <span key={tag}
                                                    className="inline-block px-2 py-0.5 bg-indigo-50 text-indigo-600 rounded-full text-xs">
                                                    {tag}
                                                </span>
                                            ))
                                            : <span className="text-xs text-slate-400">—</span>
                                        }
                                    </div>
                                </td>

                                {/* Data */}
                                <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
                                    {formatDate(doc.date)}
                                </td>

                                {/* Azioni */}
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-1">
                                        {/* Preview — always visible */}
                                        <button
                                            onClick={() => onPreview(doc)}
                                            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                                            title="Anteprima contenuto"
                                        >
                                            <Eye size={14} />
                                        </button>

                                        {/* Edit tags — uploaded only */}
                                        {doc.source === 'uploaded' && (
                                            <button
                                                onClick={() => onEditTags(doc._kbDoc)}
                                                className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-indigo-600 transition-colors"
                                                title="Modifica tag"
                                            >
                                                <Tag size={14} />
                                            </button>
                                        )}

                                        {/* Delete — uploaded only */}
                                        {doc.source === 'uploaded' && (
                                            <button
                                                onClick={() => onDelete(doc.id)}
                                                disabled={deletingId === doc.id}
                                                className="p-1.5 rounded-lg hover:bg-rose-50 text-slate-400 hover:text-rose-600 disabled:opacity-50 transition-colors"
                                                title="Elimina"
                                            >
                                                {deletingId === doc.id
                                                    ? <Loader2 size={14} className="animate-spin" />
                                                    : <Trash2 size={14} />
                                                }
                                            </button>
                                        )}
                                    </div>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    );
}


// ── Main Page ───────────────────────────────────────────────────────────────

export default function KnowledgeBasePage() {
    const [docs, setDocs] = useState([]);
    const [stats, setStats] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [dragOver, setDragOver] = useState(false);
    const [error, setError] = useState(null);
    const [editingDoc, setEditingDoc] = useState(null);
    const [previewDoc, setPreviewDoc] = useState(null);
    const [deletingId, setDeletingId] = useState(null);
    const fileInputRef = useRef(null);

    useEffect(() => { loadData(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const loadData = async () => {
        try {
            const [docsRes, statsRes] = await Promise.all([
                API.kb.list(),
                API.kb.stats(),
            ]);
            const docsData = await docsRes.json();
            setDocs(docsData.data || []);
            const statsData = await statsRes.json();
            setStats(statsData);
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

    return (
        <div className="space-y-6 max-w-5xl">
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

            {/* Upload zone */}
            <div
                onDragOver={e => { e.preventDefault(); setDragOver(true); }}
                onDragLeave={() => setDragOver(false)}
                onDrop={e => { e.preventDefault(); setDragOver(false); handleFile(e.dataTransfer.files[0]); }}
                onClick={() => fileInputRef.current?.click()}
                className={`border-2 border-dashed rounded-2xl p-10 text-center transition-all cursor-pointer select-none ${dragOver
                        ? 'border-indigo-400 bg-indigo-50'
                        : 'border-slate-300 hover:border-indigo-300 hover:bg-slate-50/80'
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

            {error && (
                <div className="flex items-center gap-2 text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-4 py-3 text-sm">
                    <AlertCircle size={16} /> {error}
                    <button onClick={() => setError(null)} className="ml-auto hover:text-rose-900">
                        <X size={14} />
                    </button>
                </div>
            )}

            {/* Documents table */}
            {docs.length > 0 && (
                <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                    <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
                        <BookOpen size={15} className="text-slate-400" />
                        <h2 className="font-semibold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                            Knowledge Base Documents
                        </h2>
                        <Badge variant="slate">{docs.length}</Badge>
                    </div>
                    <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                            <thead className="bg-slate-50">
                                <tr>
                                    {['File', 'Type', 'Size', 'Chunks', 'Tags', 'Uploaded', 'Actions'].map(h => (
                                        <th key={h}
                                            className="px-4 py-3 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                                            {h}
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                                {docs.map(doc => {
                                    const TypeIcon = FILE_TYPE_ICONS[doc.file_type] || FileText;
                                    return (
                                        <tr key={doc.id} className="hover:bg-slate-50/70 transition-colors">
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-2">
                                                    <TypeIcon size={15} className="text-slate-400 flex-shrink-0" />
                                                    <div>
                                                        <p className="font-medium text-slate-900 max-w-[200px] truncate" title={doc.filename}>
                                                            {doc.filename}
                                                        </p>
                                                        <p className="text-xs font-mono text-slate-400">{doc.id}</p>
                                                    </div>
                                                </div>
                                            </td>
                                            <td className="px-4 py-3">
                                                <Badge variant="info">{FILE_TYPE_LABELS[doc.file_type] || doc.file_type}</Badge>
                                            </td>
                                            <td className="px-4 py-3 text-slate-600">{formatBytes(doc.file_size_bytes)}</td>
                                            <td className="px-4 py-3 text-slate-600">{doc.chunk_count}</td>
                                            <td className="px-4 py-3">
                                                <div className="flex flex-wrap gap-1 max-w-[200px]">
                                                    {(doc.tags || []).map(tag => (
                                                        <span key={tag}
                                                            className="inline-block px-2 py-0.5 bg-indigo-50 text-indigo-600 rounded-full text-xs">
                                                            {tag}
                                                        </span>
                                                    ))}
                                                    {(!doc.tags || doc.tags.length === 0) && (
                                                        <span className="text-xs text-slate-400">—</span>
                                                    )}
                                                </div>
                                            </td>
                                            <td className="px-4 py-3 text-slate-500 text-xs">{formatDate(doc.uploaded_at)}</td>
                                            <td className="px-4 py-3">
                                                <div className="flex items-center gap-1">
                                                    <button
                                                        onClick={() => setPreviewDoc(doc)}
                                                        className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                                                        title="Preview content"
                                                    >
                                                        <Eye size={14} />
                                                    </button>
                                                    <button
                                                        onClick={() => setEditingDoc(doc)}
                                                        className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-indigo-600 transition-colors"
                                                        title="Edit tags"
                                                    >
                                                        <Tag size={14} />
                                                    </button>
                                                    <button
                                                        onClick={() => handleDelete(doc.id)}
                                                        disabled={deletingId === doc.id}
                                                        className="p-1.5 rounded-lg hover:bg-rose-50 text-slate-400 hover:text-rose-600 disabled:opacity-50 transition-colors"
                                                        title="Delete"
                                                    >
                                                        {deletingId === doc.id
                                                            ? <Loader2 size={14} className="animate-spin" />
                                                            : <Trash2 size={14} />
                                                        }
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

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
        </div>
    );
}
