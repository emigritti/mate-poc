import { useEffect, useState, useCallback, useRef } from 'react';
import { Loader2 } from 'lucide-react';
import { API } from '../../api.js';

const ENTITY_TYPE_COLORS = {
    system:        '#3b82f6',
    api_entity:    '#8b5cf6',
    business_term: '#f59e0b',
    state:         '#10b981',
    rule:          '#ef4444',
    field:         '#0ea5e9',
    process:       '#6366f1',
    generic:       '#94a3b8',
};

const NODE_W = 148, NODE_H = 50, COL_GAP = 195, ROW_GAP = 95;

function computeLayout(nodes) {
    const cols = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
    const positions = {};
    nodes.forEach((n, i) => {
        positions[n.id] = {
            x: (i % cols) * COL_GAP + NODE_W / 2 + 10,
            y: Math.floor(i / cols) * ROW_GAP + NODE_H / 2 + 10,
        };
    });
    return positions;
}

const REL_TYPES = [
    'TRANSITIONS_TO','DEPENDS_ON','CALLS','MAPS_TO',
    'GOVERNS','TRIGGERS','HANDLES_ERROR','DEFINED_BY','RELATED_TO',
];

export default function GraphCanvas({ seedEntityId, onSelectEntity }) {
    const [rawNodes, setRawNodes] = useState([]);
    const [rawEdges, setRawEdges] = useState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [relTypeFilter, setRelTypeFilter] = useState('');
    const [transform, setTransform] = useState({ x: 0, y: 0, k: 1 });
    const dragging = useRef(null);

    const loadGraph = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams({ limit_nodes: 60 });
            if (seedEntityId) params.set('entity_id', seedEntityId);
            if (relTypeFilter) params.set('rel_types', relTypeFilter);
            const res = await API.wiki.graph(params.toString());
            if (!res.ok) throw new Error(`API ${res.status}`);
            const data = await res.json();
            setRawNodes(data.nodes || []);
            setRawEdges(data.edges || []);
        } catch (err) {
            console.error('[GraphCanvas]', err);
            setError(err?.message ?? String(err));
        } finally { setLoading(false); }
    }, [seedEntityId, relTypeFilter]);

    useEffect(() => { loadGraph(); }, [loadGraph]);

    const positions = computeLayout(rawNodes);

    const handleWheel = useCallback((e) => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 1.12 : 0.89;
        setTransform(t => ({ ...t, k: Math.min(3, Math.max(0.15, t.k * factor)) }));
    }, []);

    const handleMouseDown = useCallback((e) => {
        if (e.button !== 0 || e.target.closest('[data-node]')) return;
        dragging.current = { x: e.clientX, y: e.clientY };
    }, []);

    const handleMouseMove = useCallback((e) => {
        if (!dragging.current) return;
        const dx = e.clientX - dragging.current.x;
        const dy = e.clientY - dragging.current.y;
        dragging.current = { x: e.clientX, y: e.clientY };
        setTransform(t => ({ ...t, x: t.x + dx, y: t.y + dy }));
    }, []);

    const stopDrag = useCallback(() => { dragging.current = null; }, []);

    return (
        <div className="flex flex-col gap-3">
            {/* Toolbar */}
            <div className="flex items-center gap-3 flex-wrap">
                <select
                    value={relTypeFilter}
                    onChange={e => setRelTypeFilter(e.target.value)}
                    className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 focus:outline-none"
                >
                    <option value="">All relationship types</option>
                    {REL_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                </select>
                <button
                    onClick={() => setTransform({ x: 0, y: 0, k: 1 })}
                    className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 hover:bg-slate-50"
                >
                    Reset view
                </button>
                {loading && <Loader2 size={14} className="animate-spin text-indigo-500" />}
                {error && <span className="text-xs text-red-500 font-medium">Error: {error}</span>}
                {!loading && !error && rawNodes.length === 0 && (
                    <span className="text-xs text-slate-400">No graph data — upload documents first.</span>
                )}
                <span className="ml-auto text-xs text-slate-400">
                    {rawNodes.length} nodes · {rawEdges.length} edges
                </span>
            </div>

            {/* SVG canvas — no external deps, pan + scroll-zoom */}
            <div
                className="rounded-xl border border-slate-200 bg-slate-50 overflow-hidden"
                style={{ height: 480, cursor: dragging.current ? 'grabbing' : 'grab', userSelect: 'none' }}
                onWheel={handleWheel}
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={stopDrag}
                onMouseLeave={stopDrag}
            >
                <svg width="100%" height="100%">
                    <defs>
                        <marker id="gc-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
                            <path d="M0,0 L0,6 L8,3 z" fill="#cbd5e1" />
                        </marker>
                    </defs>
                    <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
                        {/* Edges */}
                        {rawEdges.map(e => {
                            const sp = positions[e.source];
                            const tp = positions[e.target];
                            if (!sp || !tp) return null;
                            const mx = (sp.x + tp.x) / 2;
                            const my = (sp.y + tp.y) / 2;
                            return (
                                <g key={e.id}>
                                    <line
                                        x1={sp.x} y1={sp.y} x2={tp.x} y2={tp.y}
                                        stroke="#cbd5e1" strokeWidth={1.5}
                                        markerEnd="url(#gc-arrow)"
                                    />
                                    {e.label && (
                                        <text x={mx} y={my - 4} textAnchor="middle" fontSize={8} fill="#94a3b8">
                                            {e.label}
                                        </text>
                                    )}
                                </g>
                            );
                        })}
                        {/* Nodes */}
                        {rawNodes.map(n => {
                            const p = positions[n.id];
                            if (!p) return null;
                            const color = ENTITY_TYPE_COLORS[n.data?.entity_type] ?? '#94a3b8';
                            return (
                                <g
                                    key={n.id}
                                    data-node="1"
                                    style={{ cursor: 'pointer' }}
                                    onClick={() => onSelectEntity?.(n.id)}
                                >
                                    <rect
                                        x={p.x - NODE_W / 2} y={p.y - NODE_H / 2}
                                        width={NODE_W} height={NODE_H}
                                        rx={8} fill="white"
                                        stroke={color} strokeWidth={2}
                                    />
                                    <text
                                        x={p.x} y={p.y - 7}
                                        textAnchor="middle" fontSize={11}
                                        fontWeight="600" fill="#1e293b"
                                    >
                                        {n.data?.label ?? n.id}
                                    </text>
                                    <text
                                        x={p.x} y={p.y + 10}
                                        textAnchor="middle" fontSize={9} fill={color}
                                    >
                                        {n.data?.entity_type ?? ''}
                                    </text>
                                </g>
                            );
                        })}
                    </g>
                </svg>
            </div>
        </div>
    );
}
