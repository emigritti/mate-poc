import { NavLink } from 'react-router-dom';
import { Upload, Plug, Bot, BookOpen, FileText, CheckSquare, Trash2, Zap, Library, BookMarked, SlidersHorizontal, DatabaseZap, Settings2, Network, FlaskConical } from 'lucide-react';

const NAV_GROUPS = [
  {
    label: 'Workflow',
    items: [
      { id: 'requirements', label: 'Requirements',   icon: Upload },
      { id: 'apis',         label: 'API Systems',    icon: Plug   },
      { id: 'agent',        label: 'Agent Workspace', icon: Bot   },
    ],
  },
  {
    label: 'Knowledge Base',
    items: [
      { id: 'kb',                label: 'Knowledge Base',    icon: Library     },
      { id: 'wiki',              label: 'LLM Wiki',          icon: Network     },
      { id: 'ingestion-sources', label: 'Ingestion Sources', icon: DatabaseZap },
    ],
  },
  {
    label: 'Results',
    items: [
      { id: 'catalog',   label: 'Integration Catalog', icon: BookOpen    },
      { id: 'documents', label: 'Generated Docs',       icon: FileText    },
      { id: 'approvals', label: 'HITL Approvals',       icon: CheckSquare },
    ],
  },
  {
    label: 'Quality',
    items: [
      { id: 'eval', label: 'RAG Eval', icon: FlaskConical },
    ],
  },
  {
    label: 'Admin',
    items: [
      { id: 'reset',          label: 'Reset Tools',    icon: Trash2            },
      { id: 'project-docs',   label: 'Project Docs',   icon: BookMarked        },
      { id: 'llm-settings',   label: 'LLM Settings',   icon: SlidersHorizontal },
      { id: 'agent-settings', label: 'Agent Settings', icon: Settings2         },
    ],
  },
];

const DOT_COLOR = {
  ok: 'bg-emerald-400',
  error: 'bg-rose-500',
  null: 'bg-amber-400',
};

function ServiceDot({ status }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${DOT_COLOR[status] ?? DOT_COLOR.null}`}
    />
  );
}

export default function Sidebar({ services }) {
  return (
    <aside
      className="flex flex-col w-60 min-w-60 h-full bg-slate-900 overflow-hidden border-r border-slate-800"
      style={{ fontFamily: 'Outfit, sans-serif' }}
    >
      {/* Brand */}
      <div className="px-5 py-5 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center flex-shrink-0 shadow-lg shadow-indigo-900/50">
            <Zap size={15} className="text-white" />
          </div>
          <div>
            <p className="text-white font-semibold text-sm leading-none tracking-tight">Integration Mate</p>
            <p className="text-slate-500 text-xs mt-0.5">Agentic RAG Platform</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-5">
        {NAV_GROUPS.map(group => (
          <div key={group.label}>
            <p className="text-[10px] font-bold text-slate-600 uppercase tracking-widest px-3 mb-1.5">
              {group.label}
            </p>
            {group.items.map(item => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.id}
                  to={`/${item.id}`}
                  className={({ isActive }) =>
                    `w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-all duration-150 text-left mb-0.5 ${
                      isActive
                        ? 'bg-indigo-600 text-white font-medium shadow-md shadow-indigo-900/40'
                        : 'text-slate-400 hover:text-slate-100 hover:bg-slate-800'
                    }`
                  }
                >
                  <Icon size={15} className="flex-shrink-0" />
                  <span className="truncate">{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Service status */}
      <div className="px-5 py-4 border-t border-slate-800 space-y-2">
        <p className="text-[10px] font-bold text-slate-600 uppercase tracking-widest mb-2">Services</p>
        {[
          { label: 'Agent (4003)',      key: 'agent'     },
          { label: 'PLM API (3001)',    key: 'plm'       },
          { label: 'PIM API (3002)',    key: 'pim'       },
          { label: 'Ingestion (4006)', key: 'ingestion' },
        ].map(({ label, key }) => (
          <div key={key} className="flex items-center gap-2">
            <ServiceDot status={services[key]} />
            <span className="text-xs text-slate-500">{label}</span>
          </div>
        ))}
      </div>
    </aside>
  );
}
