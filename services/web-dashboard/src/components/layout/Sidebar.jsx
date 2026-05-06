import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, Upload, Bot, CheckSquare, BookOpen, FileText,
  Library, Network, DatabaseZap, FlaskConical,
  SlidersHorizontal, Settings2, Plug, Trash2, BookMarked,
  ChevronDown, ChevronRight, Zap,
} from 'lucide-react';
import UiModeToggle from '../pixel/UiModeToggle';

const NAV_GROUPS = [
  {
    label: 'Home',
    items: [
      { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    ],
  },
  {
    label: 'Workflow',
    items: [
      { id: 'requirements', label: 'Requirements',        icon: Upload      },
      { id: 'agent',        label: 'Agent Workspace',     icon: Bot         },
      { id: 'approvals',    label: 'HITL Approvals',      icon: CheckSquare },
      { id: 'catalog',      label: 'Integration Catalog', icon: BookOpen    },
      { id: 'documents',    label: 'Generated Docs',      icon: FileText    },
    ],
  },
  {
    label: 'Knowledge',
    items: [
      { id: 'kb',                label: 'Knowledge Base',    icon: Library     },
      { id: 'wiki',              label: 'LLM Wiki',          icon: Network     },
      { id: 'ingestion-sources', label: 'Ingestion Sources', icon: DatabaseZap },
    ],
  },
  {
    label: 'Quality',
    items: [
      { id: 'eval', label: 'RAG Eval', icon: FlaskConical },
    ],
  },
];

const SETTINGS_ITEMS = [
  { id: 'llm-settings',   label: 'LLM Settings',  icon: SlidersHorizontal },
  { id: 'agent-settings', label: 'Agent Settings', icon: Settings2         },
  { id: 'apis',           label: 'API Systems',    icon: Plug              },
  { id: 'reset',          label: 'Reset Tools',    icon: Trash2            },
  { id: 'project-docs',   label: 'Project Docs',   icon: BookMarked        },
];

const DOT_COLOR = {
  ok:    'bg-emerald-400',
  error: 'bg-rose-500',
  null:  'bg-amber-400',
};

function ServiceDot({ status }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${DOT_COLOR[status] ?? DOT_COLOR.null}`} />
  );
}

function NavItem({ id, label, Icon }) {
  const { pathname } = useLocation();
  const isActive = pathname === `/${id}`;

  return (
    <NavLink
      to={`/${id}`}
      className={`relative flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors duration-150 mb-0.5 ${
        isActive
          ? 'bg-zinc-800 text-white font-medium'
          : 'text-zinc-400 hover:text-white hover:bg-zinc-800/60'
      }`}
    >
      {isActive && (
        <span className="absolute left-0 inset-y-1.5 w-0.5 rounded-r-full bg-sky-500" />
      )}
      <Icon size={15} className="flex-shrink-0 ml-0.5" />
      <span className="truncate">{label}</span>
    </NavLink>
  );
}

export default function Sidebar({ services }) {
  const [settingsOpen, setSettingsOpen] = useState(false);

  return (
    <aside
      className="flex flex-col w-[220px] min-w-[220px] h-full bg-zinc-950 overflow-hidden border-r border-zinc-800"
      style={{ fontFamily: 'Outfit, sans-serif' }}
    >
      {/* Brand */}
      <div className="px-5 py-5 border-b border-zinc-800">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-sky-600 flex items-center justify-center flex-shrink-0">
            <Zap size={15} className="text-white" />
          </div>
          <div>
            <p className="text-white font-medium text-sm leading-none tracking-tight">Integration Mate</p>
            <p className="text-zinc-500 text-xs mt-0.5">Agentic RAG Platform</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-5">
        {NAV_GROUPS.map(group => (
          <div key={group.label}>
            <p className="text-zinc-500 text-xs uppercase tracking-wider px-3 mb-1.5">
              {group.label}
            </p>
            {group.items.map(item => (
              <NavItem key={item.id} id={item.id} label={item.label} Icon={item.icon} />
            ))}
          </div>
        ))}

        {/* Settings — collapsible */}
        <div>
          <button
            onClick={() => setSettingsOpen(o => !o)}
            className="w-full flex items-center justify-between px-3 py-1.5 mb-1 text-zinc-500 text-xs uppercase tracking-wider hover:text-zinc-300 transition-colors"
          >
            <span>Settings</span>
            {settingsOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
          {settingsOpen && SETTINGS_ITEMS.map(item => (
            <NavItem key={item.id} id={item.id} label={item.label} Icon={item.icon} />
          ))}
        </div>
      </nav>

      {/* Footer: service status + mode toggle */}
      <div className="px-4 py-4 border-t border-zinc-800 space-y-4">
        <div className="space-y-1.5">
          <p className="text-zinc-600 text-[10px] uppercase tracking-wider mb-2">Services</p>
          {[
            { label: 'Agent (4003)',     key: 'agent'     },
            { label: 'PLM (3001)',       key: 'plm'       },
            { label: 'PIM (3002)',       key: 'pim'       },
            { label: 'Ingestion (4006)', key: 'ingestion' },
          ].map(({ label, key }) => (
            <div key={key} className="flex items-center gap-2">
              <ServiceDot status={services[key]} />
              <span className="text-xs text-zinc-600">{label}</span>
            </div>
          ))}
        </div>
        <UiModeToggle />
      </div>
    </aside>
  );
}
