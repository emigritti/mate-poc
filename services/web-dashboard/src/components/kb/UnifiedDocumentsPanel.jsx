import { useState, useEffect, useRef } from 'react';
import {
    Search, Tag, FileText, Loader2, Eye, BookOpen,
    Trash2, Link, Cpu,
} from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import { formatBytes, getDocumentStatus } from './kbHelpers';

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatDate(iso) {
    try {
        return new Date(iso).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
        });
    } catch {
        return iso;
    }
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


// ── UnifiedDocumentsPanel ─────────────────────────────────────────────────────

/**
 * Shows all KB documents (uploaded + promoted integration specs) in one table.
 * Includes a client-side text search box that filters by name or tag.
 * Delete action is available only for uploaded docs.
 *
 * Props:
 *   docs        {Array}    — unified doc list (from normalizeKBDocs)
 *   onDelete    {Function} — called with doc.id
 *   deletingId  {string}   — id of the doc currently being deleted
 *   onPreview   {Function} — called with the unified doc object
 *   onEditTags  {Function} — called with doc._kbDoc
 */
export default function UnifiedDocumentsPanel({ docs, onDelete, onDeleteIntegration, deletingId, onPreview, onEditTags }) {
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
                    All KB Documents
                </h2>
                <Badge variant="slate">{docs.length}</Badge>
            </div>

            {/* Search box */}
            <div className="px-5 py-3 border-b border-slate-100">
                <div className="relative">
                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                    <input
                        type="text"
                        placeholder="Search by name or tag…"
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
                            {['Name', 'Type', 'Tags', 'Date', 'Actions'].map(h => (
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
                                        ? 'No documents match the search.'
                                        : 'No documents in the Knowledge Base.'}
                                </td>
                            </tr>
                        )}
                        {displayed.map(doc => (
                            <tr key={doc.id} className="hover:bg-slate-50/70 transition-colors">
                                {/* Name */}
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-2">
                                        {doc.source === 'url'
                                            ? <Link size={15} className="text-cyan-500 flex-shrink-0" />
                                            : doc.source === 'uploaded'
                                                ? <FileText size={15} className="text-slate-400 flex-shrink-0" />
                                                : <Cpu size={15} className="text-blue-400 flex-shrink-0" />
                                        }
                                        {doc.source === 'url' && doc.url
                                            ? <a
                                                href={doc.url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="font-medium text-cyan-700 hover:underline max-w-[220px] truncate"
                                                title={doc.url}
                                                onClick={e => e.stopPropagation()}
                                              >
                                                {doc.name}
                                              </a>
                                            : <p className="font-medium text-slate-900 max-w-[220px] truncate" title={doc.name}>
                                                {doc.name}
                                              </p>
                                        }
                                    </div>
                                </td>

                                {/* Type */}
                                <td className="px-4 py-3">
                                    {doc.source === 'url'
                                        ? <Badge variant="info">🔗 Link</Badge>
                                        : doc.source === 'uploaded'
                                            ? <Badge variant="slate">📤 Uploaded</Badge>
                                            : <Badge variant="info">⚙️ Integration</Badge>
                                    }
                                </td>

                                {/* Tags */}
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

                                {/* Date */}
                                <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">
                                    {formatDate(doc.date)}
                                </td>

                                {/* Actions */}
                                <td className="px-4 py-3">
                                    <div className="flex items-center gap-1">
                                        {/* Preview — always visible */}
                                        <button
                                            onClick={() => onPreview(doc)}
                                            className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                                            title="Preview content"
                                        >
                                            <Eye size={14} />
                                        </button>

                                        {/* Edit tags — uploaded and url entries */}
                                        {(doc.source === 'uploaded' || doc.source === 'url') && (
                                            <button
                                                onClick={() => onEditTags(doc._kbDoc)}
                                                className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-indigo-600 transition-colors"
                                                title="Edit tags"
                                            >
                                                <Tag size={14} />
                                            </button>
                                        )}

                                        {/* Delete — uploaded and url entries */}
                                        {(doc.source === 'uploaded' || doc.source === 'url') && (
                                            <button
                                                onClick={() => onDelete(doc.id)}
                                                disabled={deletingId === doc.id}
                                                className="p-1.5 rounded-lg hover:bg-rose-50 text-slate-400 hover:text-rose-600 disabled:opacity-50 transition-colors"
                                                title="Delete"
                                            >
                                                {deletingId === doc.id
                                                    ? <Loader2 size={14} className="animate-spin" />
                                                    : <Trash2 size={14} />
                                                }
                                            </button>
                                        )}

                                        {/* Remove from KB — integration docs (generative flow + HITL) */}
                                        {doc.source === 'integration' && (
                                            <button
                                                onClick={() => onDeleteIntegration(doc.id)}
                                                disabled={deletingId === doc.id}
                                                className="p-1.5 rounded-lg hover:bg-rose-50 text-slate-400 hover:text-rose-600 disabled:opacity-50 transition-colors"
                                                title="Remove from Knowledge Base"
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
