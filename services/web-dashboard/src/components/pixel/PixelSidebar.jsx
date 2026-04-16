/**
 * PixelSidebar — Navigation sidebar for pixel mode (ADR-047).
 * Same nav structure as Sidebar.jsx but styled with pixel design system.
 */
import { Zap, Upload, Globe, Bot, BookOpen, Database, List, FileText, CheckSquare, RotateCcw, BookMarked, Settings, Circle } from 'lucide-react';
import UiModeToggle from './UiModeToggle';

const NAV_GROUPS = [
  {
    label: 'WORKFLOW',
    items: [
      { id: 'requirements', label: 'Requirements', icon: Upload },
      { id: 'apis',         label: 'API Systems',  icon: Globe },
      { id: 'agent',        label: 'Agent',        icon: Bot },
    ],
  },
  {
    label: 'KNOWLEDGE',
    items: [
      { id: 'kb',                label: 'Knowledge Base',    icon: BookOpen },
      { id: 'ingestion-sources', label: 'Ingestion Sources', icon: Database },
    ],
  },
  {
    label: 'RESULTS',
    items: [
      { id: 'catalog',   label: 'Catalog',   icon: List },
      { id: 'documents', label: 'Documents', icon: FileText },
      { id: 'approvals', label: 'Approvals', icon: CheckSquare },
    ],
  },
  {
    label: 'ADMIN',
    items: [
      { id: 'reset',        label: 'Reset',        icon: RotateCcw },
      { id: 'project-docs', label: 'Project Docs', icon: BookMarked },
      { id: 'llm-settings', label: 'LLM Settings', icon: Settings },
    ],
  },
];

export default function PixelSidebar({ currentPage, onNavigate, services = {} }) {
  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={{ width: 200, minWidth: 200, background: 'var(--pixel-bg)', borderRight: '2px solid var(--pixel-border)' }}
    >
      {/* Brand */}
      <div
        className="flex items-center gap-2 px-4 py-4"
        style={{ borderBottom: '1px solid var(--pixel-border)' }}
      >
        <Zap size={16} style={{ color: 'var(--pixel-accent)' }} />
        <span className="pixel-text" style={{ color: 'var(--pixel-accent)', fontSize: 7 }}>INT. MATE</span>
      </div>

      {/* Nav groups */}
      <nav className="flex-1 overflow-y-auto p-2 space-y-3">
        {NAV_GROUPS.map(group => (
          <div key={group.label}>
            <p className="pixel-text-sm px-2 mb-1" style={{ color: 'var(--pixel-muted)', fontSize: 5 }}>
              {group.label}
            </p>
            {group.items.map(item => {
              const Icon     = item.icon;
              const isActive = currentPage === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onNavigate(item.id)}
                  className="w-full flex items-center gap-2 px-2 py-2 text-left"
                  style={{
                    background:   isActive ? 'var(--pixel-primary)' : 'transparent',
                    color:        isActive ? 'var(--pixel-bg)'      : 'var(--pixel-text)',
                    border:       isActive ? '1px solid var(--pixel-border)' : '1px solid transparent',
                    borderRadius: 0,
                    cursor: 'pointer',
                  }}
                >
                  <Icon size={11} />
                  <span className="pixel-text-sm" style={{ fontSize: 6 }}>{item.label}</span>
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Service status dots */}
      {Object.keys(services).length > 0 && (
        <div className="p-3 space-y-1" style={{ borderTop: '1px solid var(--pixel-border)' }}>
          {Object.entries(services).map(([svc, status]) => (
            <div key={svc} className="flex items-center gap-1.5">
              <Circle
                size={6}
                fill={status === 'ok' ? 'var(--pixel-primary)' : 'var(--pixel-danger)'}
                style={{ color: status === 'ok' ? 'var(--pixel-primary)' : 'var(--pixel-danger)' }}
              />
              <span className="pixel-text-sm" style={{ fontSize: 5, color: 'var(--pixel-muted)' }}>
                {svc.toUpperCase()}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Mode toggle */}
      <div className="p-3" style={{ borderTop: '1px solid var(--pixel-border)' }}>
        <UiModeToggle />
      </div>
    </div>
  );
}
