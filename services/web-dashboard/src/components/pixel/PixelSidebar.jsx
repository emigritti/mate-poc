/**
 * PixelSidebar — Navigation sidebar for pixel mode (ADR-047).
 * Same nav structure as Sidebar.jsx but styled with pixel design system.
 */
import { Upload, Globe, Bot, BookOpen, Database, List, FileText, CheckSquare, RotateCcw, BookMarked, Settings } from 'lucide-react';
import UiModeToggle from './UiModeToggle';

const NAV_GROUPS = [
  {
    label: '▌WORKFLOW',
    items: [
      { id: 'requirements', label: 'REQUIREMENTS', icon: Upload },
      { id: 'apis',         label: 'API SYSTEMS',  icon: Globe },
      { id: 'agent',        label: 'AGENT',        icon: Bot },
    ],
  },
  {
    label: '▌KNOWLEDGE',
    items: [
      { id: 'kb',                label: 'KNOW. BASE',  icon: BookOpen },
      { id: 'ingestion-sources', label: 'INGESTION',   icon: Database },
    ],
  },
  {
    label: '▌RESULTS',
    items: [
      { id: 'catalog',   label: 'CATALOG',   icon: List },
      { id: 'documents', label: 'DOCUMENTS', icon: FileText },
      { id: 'approvals', label: 'APPROVALS', icon: CheckSquare },
    ],
  },
  {
    label: '▌ADMIN',
    items: [
      { id: 'reset',        label: 'RESET',      icon: RotateCcw },
      { id: 'project-docs', label: 'PROJ. DOCS', icon: BookMarked },
      { id: 'llm-settings', label: 'LLM CONFIG', icon: Settings },
    ],
  },
];

const BORDER_COLOR = 'var(--pixel-border)';
const BG           = 'var(--pixel-bg)';
const ACCENT       = 'var(--pixel-accent)';
const TEXT         = 'var(--pixel-text)';
const MUTED        = 'var(--pixel-muted)';

export default function PixelSidebar({ currentPage, onNavigate, services = {} }) {
  return (
    <div
      className="flex flex-col h-full overflow-hidden"
      style={{ width: 210, minWidth: 210, background: BG, borderRight: `3px solid ${BORDER_COLOR}` }}
    >
      {/* C64 boot header */}
      <div
        className="px-3 pt-3 pb-2"
        style={{ borderBottom: `2px solid ${BORDER_COLOR}` }}
      >
        <p className="pixel-text" style={{ color: ACCENT, fontSize: 6, lineHeight: 1.8 }}>
          **** INT.MATE ****
        </p>
        <p className="pixel-text" style={{ color: TEXT, fontSize: 5, lineHeight: 1.8 }}>
          COMMODORE 64  BASIC
        </p>
        <p className="pixel-text" style={{ color: MUTED, fontSize: 5, lineHeight: 1.8 }}>
          ══════════════════
        </p>
        <p className="pixel-text c64-cursor" style={{ color: TEXT, fontSize: 5, lineHeight: 1.8 }}>
          READY.
        </p>
      </div>

      {/* Nav groups */}
      <nav className="flex-1 overflow-y-auto px-2 py-3 space-y-3 pixel-scroll">
        {NAV_GROUPS.map(group => (
          <div key={group.label}>
            <p className="pixel-text-sm px-1 mb-1" style={{ color: ACCENT, fontSize: 5 }}>
              {group.label}
            </p>
            {group.items.map(item => {
              const Icon     = item.icon;
              const isActive = currentPage === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => onNavigate(item.id)}
                  className="w-full flex items-center gap-2 px-2 py-1.5 text-left"
                  style={{
                    background:   isActive ? BORDER_COLOR : 'transparent',
                    color:        isActive ? BG           : TEXT,
                    border:       'none',
                    borderLeft:   isActive ? `3px solid ${ACCENT}` : '3px solid transparent',
                    borderRadius: 0,
                    cursor:       'pointer',
                    textShadow:   isActive ? 'none' : '0 0 6px rgba(136,136,255,0.4)',
                  }}
                >
                  <span style={{ fontSize: 8, color: isActive ? BG : MUTED, minWidth: 10 }}>
                    {isActive ? '►' : ' '}
                  </span>
                  <Icon size={10} />
                  <span className="pixel-text-sm" style={{ fontSize: 5.5 }}>{item.label}</span>
                </button>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Service status — PETSCII style */}
      {Object.keys(services).length > 0 && (
        <div className="px-3 py-2 space-y-0.5" style={{ borderTop: `1px solid ${BORDER_COLOR}` }}>
          <p className="pixel-text-sm" style={{ color: ACCENT, fontSize: 5 }}>SYS STATUS</p>
          {Object.entries(services).map(([svc, status]) => (
            <div key={svc} className="flex items-center gap-1.5">
              <span style={{ fontSize: 8, color: status === 'ok' ? 'var(--pixel-primary)' : 'var(--pixel-danger)', lineHeight: 1 }}>
                {status === 'ok' ? '●' : '○'}
              </span>
              <span className="pixel-text-sm" style={{ fontSize: 5, color: status === 'ok' ? TEXT : 'var(--pixel-danger)' }}>
                {svc.toUpperCase()}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Mode toggle */}
      <div className="p-3" style={{ borderTop: `2px solid ${BORDER_COLOR}` }}>
        <UiModeToggle />
      </div>
    </div>
  );
}
