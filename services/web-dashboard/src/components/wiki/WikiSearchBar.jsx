import { useState, useCallback } from 'react';
import { Search, Loader2 } from 'lucide-react';
import { API } from '../../api.js';

export default function WikiSearchBar({ onSelect }) {
    const [q, setQ] = useState('');
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(false);

    const search = useCallback(async (value) => {
        if (value.trim().length < 2) { setResults([]); return; }
        setLoading(true);
        try {
            const res = await API.wiki.search(value);
            const data = await res.json();
            setResults(data.entities || []);
        } catch { setResults([]); }
        finally { setLoading(false); }
    }, []);

    const handleChange = (e) => {
        const v = e.target.value;
        setQ(v);
        search(v);
    };

    return (
        <div className="relative">
            <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                    type="text"
                    value={q}
                    onChange={handleChange}
                    placeholder="Search entities…"
                    className="w-full pl-9 pr-4 py-2 text-sm border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300"
                />
                {loading && <Loader2 size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 animate-spin" />}
            </div>
            {results.length > 0 && (
                <div className="absolute z-20 left-0 right-0 mt-1 bg-white border border-slate-200 rounded-lg shadow-lg max-h-56 overflow-y-auto">
                    {results.map(e => (
                        <button
                            key={e.entity_id}
                            onClick={() => { onSelect(e); setResults([]); setQ(''); }}
                            className="w-full text-left px-3 py-2 text-sm hover:bg-indigo-50 flex items-center justify-between gap-2"
                        >
                            <span className="font-medium text-slate-800">{e.name}</span>
                            <span className="text-xs text-slate-400">{e.entity_type}</span>
                        </button>
                    ))}
                </div>
            )}
        </div>
    );
}
