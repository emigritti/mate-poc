import { useState } from 'react';
import { Pin, FileText, FileType, FileSpreadsheet, Presentation, Image, ChevronDown, ChevronUp } from 'lucide-react';

const MAX_PINNED = 3;

const FILE_TYPE_ICONS = {
    pdf:  FileText,
    docx: FileType,
    xlsx: FileSpreadsheet,
    pptx: Presentation,
    md:   FileText,
    png:  Image,
    jpg:  Image,
    svg:  Image,
};

const FILE_TYPE_LABELS = {
    pdf:  'PDF',
    docx: 'Word',
    xlsx: 'Excel',
    pptx: 'PowerPoint',
    md:   'Markdown',
    png:  'PNG',
    jpg:  'JPG',
    svg:  'SVG',
};

/**
 * PinnedRefsSelector — lets the user pin up to MAX_PINNED KB documents
 * whose chunks will be injected verbatim into the LLM prompt as
 * "PINNED REFERENCES", regardless of RAG retrieval score.
 *
 * Props:
 *   docs      — array of KBDocument (file_type !== 'url' already filtered by parent)
 *   selected  — array of doc id strings currently pinned
 *   onChange  — callback(newSelectedIds: string[])
 */
export default function PinnedRefsSelector({ docs = [], selected = [], onChange }) {
    const [open, setOpen] = useState(false);

    const toggle = (id) => {
        if (selected.includes(id)) {
            onChange(selected.filter(x => x !== id));
        } else if (selected.length < MAX_PINNED) {
            onChange([...selected, id]);
        }
    };

    const count = selected.length;

    return (
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
            {/* Header / toggle */}
            <button
                type="button"
                onClick={() => setOpen(v => !v)}
                className="w-full flex items-center justify-between px-4 py-3 text-sm text-slate-700 hover:bg-slate-50 transition-colors"
            >
                <span className="flex items-center gap-2 font-medium">
                    <Pin size={14} className="text-indigo-500" />
                    Pinned References
                    <span className={`inline-flex items-center justify-center rounded-full px-2 py-0.5 text-xs font-semibold ${
                        count > 0
                            ? 'bg-indigo-100 text-indigo-700'
                            : 'bg-slate-100 text-slate-500'
                    }`}>
                        {count}/{MAX_PINNED}
                    </span>
                </span>
                <span className="text-slate-400">
                    {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </span>
            </button>

            {/* Collapsible doc list */}
            {open && (
                <div className="border-t border-slate-100 divide-y divide-slate-50 max-h-60 overflow-y-auto">
                    {docs.length === 0 ? (
                        <p className="px-4 py-3 text-xs text-slate-400">
                            No documents in the Knowledge Base yet.
                        </p>
                    ) : (
                        docs.map(doc => {
                            const isSelected = selected.includes(doc.id);
                            const isDisabled = !isSelected && count >= MAX_PINNED;
                            const Icon = FILE_TYPE_ICONS[doc.file_type] ?? FileText;
                            const label = FILE_TYPE_LABELS[doc.file_type] ?? doc.file_type?.toUpperCase();

                            return (
                                <label
                                    key={doc.id}
                                    className={`flex items-start gap-3 px-4 py-2.5 cursor-pointer transition-colors ${
                                        isDisabled
                                            ? 'opacity-40 cursor-not-allowed'
                                            : isSelected
                                                ? 'bg-indigo-50/60'
                                                : 'hover:bg-slate-50'
                                    }`}
                                >
                                    <input
                                        type="checkbox"
                                        checked={isSelected}
                                        disabled={isDisabled}
                                        onChange={() => toggle(doc.id)}
                                        className="mt-0.5 accent-indigo-600 flex-shrink-0"
                                    />
                                    <Icon size={14} className="mt-0.5 text-slate-400 flex-shrink-0" />
                                    <div className="min-w-0">
                                        <p className="text-xs font-medium text-slate-700 truncate leading-tight">
                                            {doc.filename}
                                        </p>
                                        <p className="text-xs text-slate-400 mt-0.5">
                                            {label}
                                            {doc.chunk_count != null && ` · ${doc.chunk_count} chunk${doc.chunk_count !== 1 ? 's' : ''}`}
                                        </p>
                                        {doc.content_preview && (
                                            <p className="text-xs text-slate-400 mt-0.5 truncate">
                                                {doc.content_preview.slice(0, 80)}…
                                            </p>
                                        )}
                                    </div>
                                </label>
                            );
                        })
                    )}
                </div>
            )}

            {/* Selected summary (visible even when collapsed) */}
            {count > 0 && !open && (
                <div className="border-t border-slate-100 px-4 py-2 flex flex-wrap gap-1">
                    {selected.map(id => {
                        const doc = docs.find(d => d.id === id);
                        return doc ? (
                            <span
                                key={id}
                                className="inline-flex items-center gap-1 text-xs bg-indigo-100 text-indigo-700 rounded-full px-2 py-0.5"
                            >
                                <Pin size={10} />
                                {doc.filename.length > 24 ? doc.filename.slice(0, 22) + '…' : doc.filename}
                            </span>
                        ) : null;
                    })}
                </div>
            )}
        </div>
    );
}
