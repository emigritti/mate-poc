import { FolderOpen } from 'lucide-react';
import UiModeToggle from '../pixel/UiModeToggle';
import { useProject } from '../../context/ProjectContext.jsx';

export default function TopBar({ title, subtitle }) {
  const { activeProjectId, setActiveProjectId, projects } = useProject();

  return (
    <header className="flex items-center justify-between px-6 py-3 bg-white border-b border-slate-200 flex-shrink-0">
      <div>
        <h1
          className="text-slate-900 font-semibold text-lg leading-tight"
          style={{ fontFamily: 'Outfit, sans-serif' }}
        >
          {title}
        </h1>
        <p className="text-slate-400 text-xs mt-0.5">{subtitle}</p>
      </div>

      <div className="flex items-center gap-2">
        <UiModeToggle />

        <div className="flex items-center gap-2 pl-3 border-l border-slate-200">
          <FolderOpen size={14} className="text-indigo-500" />
          <select
            value={activeProjectId ?? ''}
            onChange={e => setActiveProjectId(e.target.value || null)}
            className="text-sm font-medium text-slate-700 bg-transparent border border-slate-200 rounded-lg px-2 py-1 outline-none cursor-pointer focus:border-indigo-400"
          >
            <option value="">All Projects</option>
            {projects.map(p => (
              <option key={p.prefix} value={p.prefix}>
                {p.client_name} ({p.prefix})
              </option>
            ))}
          </select>
        </div>
      </div>
    </header>
  );
}
