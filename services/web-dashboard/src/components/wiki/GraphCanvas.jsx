import { useEffect, useState, useCallback } from 'react';
import { Loader2 } from 'lucide-react';
import {
    ReactFlow,
    Background,
    Controls,
    MiniMap,
    useNodesState,
    useEdgesState,
    MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
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

function layoutNodes(rawNodes) {
    const cols = Math.ceil(Math.sqrt(rawNodes.length));
    return rawNodes.map((n, i) => ({
        ...n,
        position: {
            x: (i % cols) * 180,
            y: Math.floor(i / cols) * 100,
        },
    }));
}

export default function GraphCanvas({ seedEntityId, onSelectEntity }) {
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState(null);
    const [relTypeFilter, setRelTypeFilter] = useState('');
    const [rawNodes, setRawNodes] = useState([]);

    const loadGraph = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const params = new URLSearchParams({ limit_nodes: 50 });
            if (seedEntityId) params.set('entity_id', seedEntityId);
            if (relTypeFilter) params.set('rel_types', relTypeFilter);
            const res = await API.wiki.graph(params.toString());
            if (!res.ok) throw new Error(`API error ${res.status}`);
            const data = await res.json();

            setRawNodes(data.nodes || []);

            const rfNodes = layoutNodes((data.nodes || []).map(n => ({
                id: n.id,
                type: 'default',
                data: {
                    label: `${n.data.label} (${n.data.entity_type})`,
                },
                style: {
                    background: '#fff',
                    border: `2px solid ${ENTITY_TYPE_COLORS[n.data.entity_type] ?? '#94a3b8'}`,
                    borderRadius: 8,
                    fontSize: 11,
                    minWidth: 120,
                    padding: '4px 8px',
                },
            })));

            const rfEdges = (data.edges || []).map(e => ({
                id: e.id,
                source: e.source,
                target: e.target,
                label: e.label,
                markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
                style: { strokeWidth: 1.5, stroke: '#94a3b8' },
                labelStyle: { fontSize: 9, fill: '#64748b' },
                animated: e.data?.rel_type === 'TRANSITIONS_TO',
            }));

            setNodes(rfNodes);
            setEdges(rfEdges);
        } catch (err) {
            console.error('[GraphCanvas]', err);
            setError(err?.message ?? String(err));
        } finally { setLoading(false); }
    }, [seedEntityId, relTypeFilter, setNodes, setEdges]);

    useEffect(() => { loadGraph(); }, [loadGraph]);

    const handleNodeClick = useCallback((_, node) => {
        onSelectEntity?.(node.id);
    }, [onSelectEntity]);

    return (
        <div className="flex flex-col h-full min-h-[500px] gap-3">
            {/* Toolbar */}
            <div className="flex items-center gap-3 flex-wrap">
                <select
                    value={relTypeFilter}
                    onChange={e => setRelTypeFilter(e.target.value)}
                    className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 focus:outline-none"
                >
                    <option value="">All relationship types</option>
                    {['TRANSITIONS_TO','DEPENDS_ON','CALLS','MAPS_TO','GOVERNS','TRIGGERS','HANDLES_ERROR','DEFINED_BY','RELATED_TO'].map(t => (
                        <option key={t} value={t}>{t}</option>
                    ))}
                </select>
                {loading && <Loader2 size={14} className="animate-spin text-indigo-500" />}
                {!loading && !error && nodes.length === 0 && (
                    <span className="text-xs text-slate-400">No graph data. Upload and process documents first.</span>
                )}
                {error && (
                    <span className="text-xs text-red-500 font-medium">Graph render error: {error}</span>
                )}
                <span className="ml-auto text-xs text-slate-400">{nodes.length} nodes · {edges.length} edges</span>
            </div>

            {/* Fallback table — shown when ReactFlow has no nodes but API returned data */}
            {!loading && nodes.length === 0 && rawNodes.length > 0 && (
                <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
                    <p className="text-xs font-medium text-amber-800 mb-3">
                        ReactFlow canvas unavailable — showing entity list ({rawNodes.length} entities):
                    </p>
                    <div className="flex flex-wrap gap-2">
                        {rawNodes.map(n => (
                            <button
                                key={n.id}
                                onClick={() => onSelectEntity?.(n.id)}
                                className="px-2 py-1 rounded-lg text-xs border"
                                style={{ borderColor: ENTITY_TYPE_COLORS[n.data.entity_type] ?? '#94a3b8', color: ENTITY_TYPE_COLORS[n.data.entity_type] ?? '#94a3b8' }}
                            >
                                {n.data.label}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            {/* React Flow canvas */}
            <div className="flex-1 rounded-xl border border-slate-200 overflow-hidden bg-slate-50" style={{ minHeight: 460 }}>
                <ReactFlow
                    nodes={nodes}
                    edges={edges}
                    onNodesChange={onNodesChange}
                    onEdgesChange={onEdgesChange}
                    onNodeClick={handleNodeClick}
                    fitView
                    fitViewOptions={{ padding: 0.3 }}
                    minZoom={0.2}
                    maxZoom={2}
                >
                    <Background />
                    <Controls />
                    <MiniMap nodeColor={n => {
                        const style = n.style?.border;
                        return style ? style.replace('2px solid ', '') : '#94a3b8';
                    }} />
                </ReactFlow>
            </div>
        </div>
    );
}
