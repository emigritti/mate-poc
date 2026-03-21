import { useState } from 'react';
import { X, AlertCircle, CheckCircle, Loader2 } from 'lucide-react';
import { API } from '../../api.js';

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

export default TagEditModal;
