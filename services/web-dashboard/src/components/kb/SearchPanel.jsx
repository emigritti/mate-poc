import { useState } from 'react';
import { Search, Loader2, AlertCircle } from 'lucide-react';
import Badge from '../ui/Badge.jsx';
import { API } from '../../api.js';

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

export default SearchPanel;
