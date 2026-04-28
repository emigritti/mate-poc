import { useState, useEffect } from 'react';
import { Network, List, Info, GitBranch, RefreshCw, Loader2 } from 'lucide-react';
import EntityList from '../wiki/EntityList.jsx';
import EntityDetail from '../wiki/EntityDetail.jsx';
import GraphCanvas from '../wiki/GraphCanvas.jsx';
import WikiSearchBar from '../wiki/WikiSearchBar.jsx';
import { API } from '../../api.js';

export default function WikiPage() {
    const [activeTab, setActiveTab] = useState('entities');
    const [selectedEntityId, setSelectedEntityId] = useState(null);
    const [stats, setStats] = useState(null);
    const [rebuilding, setRebuilding] = useState(false);
    const [rebuildMsg, setRebuildMsg] = useState(null);

    useEffect(() => {
        API.wiki.stats()
            .then(r => r.json())
            .then(setStats)
            .catch(() => {});
    }, []);

    const handleSelectEntity = (entityOrId) => {
        const id = typeof entityOrId === 'string' ? entityOrId : entityOrId?.entity_id;
        if (id) { setSelectedEntityId(id); setActiveTab('detail'); }
    };

    const handleRebuild = async () => {
        if (!confirm('Trigger a full wiki graph rebuild? This runs in the background.')) return;
        setRebuilding(true); setRebuildMsg(null);
        try {
            const res = await API.wiki.rebuild();
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Rebuild failed');
            setRebuildMsg(`Job ${data.job_id} queued.`);
        } catch (e) {
            setRebuildMsg(`Error: ${e.message}`);
        } finally {
            setRebuilding(false);
        }
    };

    const TABS = [
        { id: 'entities', label: 'Entities', icon: List },
        { id: 'detail',   label: 'Detail',   icon: Info },
        { id: 'graph',    label: 'Graph',     icon: GitBranch },
    ];

    return (
        <div className="space-y-4 max-w-6xl">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Network size={20} className="text-indigo-500" />
                    <h1 className="text-xl font-bold text-slate-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
                        LLM Wiki
                    </h1>
                    {stats && (
                        <span className="ml-2 text-xs text-slate-400">
                            {stats.total_entities} entities · {stats.total_relationships} relationships
                        </span>
                    )}
                </div>
                <div className="flex items-center gap-3">
                    <div className="w-64">
                        <WikiSearchBar onSelect={handleSelectEntity} />
                    </div>
                    <button
                        onClick={handleRebuild}
                        disabled={rebuilding}
                        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50"
                    >
                        {rebuilding
                            ? <Loader2 size={12} className="animate-spin" />
                            : <RefreshCw size={12} />
                        }
                        Rebuild
                    </button>
                </div>
            </div>

            {rebuildMsg && (
                <div className="text-xs text-indigo-700 bg-indigo-50 border border-indigo-200 rounded-lg px-3 py-2">
                    {rebuildMsg}
                </div>
            )}

            {/* Stats mini-bar */}
            {stats && stats.entity_types?.length > 0 && (
                <div className="flex flex-wrap gap-2">
                    {stats.entity_types.slice(0, 6).map(t => (
                        <span key={t.type} className="px-2.5 py-0.5 bg-white border border-slate-200 rounded-full text-xs text-slate-600">
                            {t.type} <strong className="text-slate-800">{t.count}</strong>
                        </span>
                    ))}
                </div>
            )}

            {/* Tabs */}
            <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="flex border-b border-slate-200">
                    {TABS.map(t => (
                        <button
                            key={t.id}
                            onClick={() => setActiveTab(t.id)}
                            className={`flex items-center gap-2 px-5 py-3 text-sm font-medium border-b-2 -mb-px transition-colors ${
                                activeTab === t.id
                                    ? 'border-indigo-500 text-indigo-600'
                                    : 'border-transparent text-slate-500 hover:text-slate-700'
                            }`}
                        >
                            <t.icon size={14} />
                            {t.label}
                        </button>
                    ))}
                </div>

                <div className="p-6">
                    {activeTab === 'entities' && (
                        <EntityList onSelectEntity={handleSelectEntity} />
                    )}
                    {activeTab === 'detail' && (
                        <EntityDetail
                            entityId={selectedEntityId}
                            onNavigate={handleSelectEntity}
                        />
                    )}
                    {activeTab === 'graph' && (
                        <GraphCanvas
                            seedEntityId={selectedEntityId}
                            onSelectEntity={handleSelectEntity}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}
