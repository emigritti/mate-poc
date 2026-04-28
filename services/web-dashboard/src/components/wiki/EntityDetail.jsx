import { useEffect, useState } from 'react';
import { Loader2, ArrowRight, ArrowLeft, FileText } from 'lucide-react';
import EntityTypeBadge from './EntityTypeBadge.jsx';
import RelTypeBadge from './RelTypeBadge.jsx';
import { API } from '../../api.js';

export default function EntityDetail({ entityId, onNavigate }) {
    const [data, setData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        if (!entityId) return;
        let cancelled = false;
        (async () => {
            setLoading(true); setError(null);
            try {
                const res = await API.wiki.entity(entityId);
                if (!res.ok) throw new Error(`Entity not found (${res.status})`);
                const d = await res.json();
                if (!cancelled) setData(d);
            } catch (e) {
                if (!cancelled) setError(e.message);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [entityId]);

    if (!entityId) return <p className="text-sm text-slate-400 text-center py-10">Select an entity from the list or graph to view details.</p>;
    if (loading) return <div className="flex justify-center py-12"><Loader2 size={24} className="animate-spin text-indigo-500" /></div>;
    if (error) return <p className="text-sm text-rose-600 text-center py-6">{error}</p>;
    if (!data) return null;

    const { entity, outgoing_edges, incoming_edges, chunk_previews } = data;

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h2 className="text-xl font-bold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                        {entity.name}
                    </h2>
                    <div className="flex items-center gap-2 mt-1">
                        <EntityTypeBadge type={entity.entity_type} />
                        <span className="text-xs text-slate-400">{entity.chunk_count} chunks</span>
                        {entity.tags_csv && <span className="text-xs text-slate-400">· {entity.tags_csv}</span>}
                    </div>
                </div>
            </div>

            {/* Outgoing edges */}
            {outgoing_edges.length > 0 && (
                <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-2">
                        <ArrowRight size={14} className="text-indigo-500" /> Outgoing ({outgoing_edges.length})
                    </h3>
                    <div className="space-y-1">
                        {outgoing_edges.map(r => (
                            <div key={r.rel_id} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-50 border border-slate-100 text-sm">
                                <RelTypeBadge type={r.rel_type} />
                                <button
                                    onClick={() => onNavigate(r.to_entity_id)}
                                    className="text-indigo-600 hover:underline font-medium"
                                >
                                    {r.to_entity_id.replace('ENT-', '')}
                                </button>
                                <span className="ml-auto text-xs text-slate-300">w:{r.weight}</span>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Incoming edges */}
            {incoming_edges.length > 0 && (
                <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-2">
                        <ArrowLeft size={14} className="text-slate-500" /> Incoming ({incoming_edges.length})
                    </h3>
                    <div className="space-y-1">
                        {incoming_edges.map(r => (
                            <div key={r.rel_id} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-50/60 border border-slate-100 text-sm">
                                <button
                                    onClick={() => onNavigate(r.from_entity_id)}
                                    className="text-indigo-600 hover:underline font-medium"
                                >
                                    {r.from_entity_id.replace('ENT-', '')}
                                </button>
                                <RelTypeBadge type={r.rel_type} />
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Chunk previews */}
            {chunk_previews.length > 0 && (
                <div>
                    <h3 className="text-sm font-semibold text-slate-700 mb-2 flex items-center gap-2">
                        <FileText size={14} className="text-slate-500" /> Source Chunks
                    </h3>
                    <div className="space-y-2">
                        {chunk_previews.map(c => (
                            <div key={c.chunk_id} className="p-3 rounded-lg bg-amber-50 border border-amber-100">
                                {c.semantic_type && (
                                    <span className="text-xs text-amber-700 font-medium block mb-1">{c.semantic_type}</span>
                                )}
                                <p className="text-sm text-slate-700 leading-relaxed line-clamp-4">{c.text}</p>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {outgoing_edges.length === 0 && incoming_edges.length === 0 && chunk_previews.length === 0 && (
                <p className="text-sm text-slate-400 text-center py-4">No edges or chunk previews found for this entity.</p>
            )}
        </div>
    );
}
