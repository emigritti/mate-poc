import { useState, useEffect, useCallback } from 'react';
import { Loader2, ChevronLeft, ChevronRight } from 'lucide-react';
import EntityTypeBadge from './EntityTypeBadge.jsx';
import { API } from '../../api.js';

const ENTITY_TYPES = ['system', 'api_entity', 'business_term', 'state', 'rule', 'field', 'process', 'generic'];
const PAGE_SIZE = 20;

export default function EntityList({ onSelectEntity }) {
    const [entities, setEntities] = useState([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [offset, setOffset] = useState(0);
    const [typeFilter, setTypeFilter] = useState('');
    const [tagFilter, setTagFilter] = useState('');

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const params = new URLSearchParams({ limit: PAGE_SIZE, offset });
            if (typeFilter) params.set('entity_type', typeFilter);
            if (tagFilter.trim()) params.set('tags', tagFilter.trim());
            const res = await API.wiki.entities(params.toString());
            const data = await res.json();
            setEntities(data.entities || []);
            setTotal(data.total || 0);
        } catch { setEntities([]); }
        finally { setLoading(false); }
    }, [offset, typeFilter, tagFilter]);

    useEffect(() => { load(); }, [load]);

    const resetPagination = () => setOffset(0);

    return (
        <div className="space-y-4">
            {/* Filters */}
            <div className="flex flex-wrap gap-3">
                <select
                    value={typeFilter}
                    onChange={e => { setTypeFilter(e.target.value); resetPagination(); }}
                    className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-300"
                >
                    <option value="">All types</option>
                    {ENTITY_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                <input
                    type="text"
                    value={tagFilter}
                    onChange={e => { setTagFilter(e.target.value); resetPagination(); }}
                    placeholder="Filter by tag…"
                    className="text-sm border border-slate-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-300"
                />
                <span className="ml-auto text-xs text-slate-400 self-center">{total} total</span>
            </div>

            {/* Table */}
            {loading ? (
                <div className="flex justify-center py-12">
                    <Loader2 size={24} className="animate-spin text-indigo-500" />
                </div>
            ) : entities.length === 0 ? (
                <p className="text-sm text-slate-400 text-center py-10">No entities found. Upload documents to build the wiki graph.</p>
            ) : (
                <div className="overflow-x-auto rounded-xl border border-slate-200">
                    <table className="w-full text-sm">
                        <thead className="bg-slate-50 border-b border-slate-200">
                            <tr>
                                <th className="text-left px-4 py-2.5 font-medium text-slate-600">Name</th>
                                <th className="text-left px-4 py-2.5 font-medium text-slate-600">Type</th>
                                <th className="text-left px-4 py-2.5 font-medium text-slate-600">Chunks</th>
                                <th className="text-left px-4 py-2.5 font-medium text-slate-600">Tags</th>
                            </tr>
                        </thead>
                        <tbody>
                            {entities.map((e, i) => (
                                <tr
                                    key={e.entity_id}
                                    onClick={() => onSelectEntity(e)}
                                    className={`cursor-pointer hover:bg-indigo-50 transition-colors ${i % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'}`}
                                >
                                    <td className="px-4 py-2.5 font-medium text-indigo-700">{e.name}</td>
                                    <td className="px-4 py-2.5"><EntityTypeBadge type={e.entity_type} /></td>
                                    <td className="px-4 py-2.5 text-slate-500">{e.chunk_count ?? '-'}</td>
                                    <td className="px-4 py-2.5 text-slate-400 text-xs truncate max-w-[180px]">{e.tags_csv || '-'}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Pagination */}
            {total > PAGE_SIZE && (
                <div className="flex items-center justify-between text-sm text-slate-600">
                    <button
                        disabled={offset === 0}
                        onClick={() => setOffset(o => Math.max(0, o - PAGE_SIZE))}
                        className="flex items-center gap-1 px-3 py-1.5 border rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                        <ChevronLeft size={14} /> Prev
                    </button>
                    <span className="text-xs text-slate-400">
                        {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
                    </span>
                    <button
                        disabled={offset + PAGE_SIZE >= total}
                        onClick={() => setOffset(o => o + PAGE_SIZE)}
                        className="flex items-center gap-1 px-3 py-1.5 border rounded-lg hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                        Next <ChevronRight size={14} />
                    </button>
                </div>
            )}
        </div>
    );
}
