import { useState } from 'react';
import { Loader2, Link } from 'lucide-react';
import { toast } from 'sonner';
import { API } from '../../api.js';

export default function AddUrlForm({ onAdded }) {
    const [url, setUrl] = useState('');
    const [title, setTitle] = useState('');
    const [tagsInput, setTagsInput] = useState('');
    const [adding, setAdding] = useState(false);

    const handleSubmit = async (e) => {
        e.preventDefault();
        const cleanUrl = url.trim();
        const tags = tagsInput.split(',').map(t => t.trim()).filter(Boolean);
        if (!cleanUrl) return;
        if (tags.length === 0) { toast.error('At least one tag is required.'); return; }
        setAdding(true);
        try {
            const res = await API.kb.addUrl({
                url: cleanUrl,
                title: title.trim() || null,
                tags,
            });
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                throw new Error(d.detail || `Failed (${res.status})`);
            }
            setUrl(''); setTitle(''); setTagsInput('');
            toast.success('URL added to Knowledge Base.');
            onAdded();
        } catch (err) {
            toast.error(err.message);
        } finally {
            setAdding(false);
        }
    };

    return (
        <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-3">
                <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                        URL <span className="text-rose-500">*</span>
                    </label>
                    <input
                        type="url"
                        placeholder="https://docs.example.com/api-reference"
                        value={url}
                        onChange={e => setUrl(e.target.value)}
                        required
                        className="w-full text-sm px-3 py-2 border border-slate-300 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100"
                    />
                </div>
                <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                        Title <span className="text-slate-400">(optional)</span>
                    </label>
                    <input
                        type="text"
                        placeholder="e.g. Salsify Integration Guide"
                        value={title}
                        onChange={e => setTitle(e.target.value)}
                        maxLength={200}
                        className="w-full text-sm px-3 py-2 border border-slate-300 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100"
                    />
                </div>
                <div>
                    <label className="block text-xs font-medium text-slate-600 mb-1">
                        Tags <span className="text-rose-500">*</span>
                        <span className="text-slate-400 font-normal ml-1">(comma-separated)</span>
                    </label>
                    <input
                        type="text"
                        placeholder="salsify, api, integration"
                        value={tagsInput}
                        onChange={e => setTagsInput(e.target.value)}
                        className="w-full text-sm px-3 py-2 border border-slate-300 rounded-lg outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-100"
                    />
                </div>
            </div>
            <button
                type="submit"
                disabled={adding || !url.trim()}
                className="flex items-center gap-2 px-4 py-2 bg-cyan-600 text-white rounded-lg text-sm font-medium hover:bg-cyan-700 disabled:opacity-50 transition-colors"
            >
                {adding ? <Loader2 size={14} className="animate-spin" /> : <Link size={14} />}
                {adding ? 'Adding…' : 'Add to KB'}
            </button>
        </form>
    );
}
