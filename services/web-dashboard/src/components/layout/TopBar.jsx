import { Bell, FolderOpen } from 'lucide-react';
import { useLocation, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useProject } from '../../context/ProjectContext.jsx';
import { ROUTE_META } from '../../router.jsx';
import { API } from '../../api.js';

export default function TopBar() {
  const location = useLocation();
  const { activeProjectId, setActiveProjectId, projects } = useProject();

  const meta = ROUTE_META[location.pathname] ?? {};
  const pageTitle = meta.title
    ?? location.pathname.replace(/^\//, '').replace(/-/g, ' ');

  const { data: pendingApprovals = [] } = useQuery({
    queryKey: ['approvals', 'pending'],
    queryFn: async () => {
      const res = await API.approvals.pending();
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : [];
    },
    refetchInterval: 15000,
  });

  const pendingCount = pendingApprovals.length;

  return (
    <header
      className="flex items-center justify-between px-6 h-14 bg-white border-b border-zinc-200 flex-shrink-0"
      style={{ fontFamily: 'Outfit, sans-serif' }}
    >
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm">
        <Link to="/dashboard" className="text-zinc-400 hover:text-zinc-600 transition-colors text-xs">
          Home
        </Link>
        <span className="text-zinc-300 text-xs">/</span>
        <span className="text-zinc-900 font-semibold capitalize text-sm">{pageTitle}</span>
      </nav>

      {/* Right actions */}
      <div className="flex items-center gap-3">
        {/* Project selector */}
        <div className="flex items-center gap-2">
          <FolderOpen size={14} className="text-zinc-400" />
          <select
            value={activeProjectId ?? ''}
            onChange={e => setActiveProjectId(e.target.value || null)}
            className="text-sm text-zinc-700 bg-transparent border border-zinc-200 rounded-lg px-2 py-1 outline-none cursor-pointer focus:border-sky-400 transition-colors"
          >
            <option value="">All Projects</option>
            {projects.map(p => (
              <option key={p.prefix} value={p.prefix}>
                {p.client_name} ({p.prefix})
              </option>
            ))}
          </select>
        </div>

        {/* Notification bell */}
        <Link
          to="/approvals"
          className="relative p-2 rounded-lg text-zinc-400 hover:text-zinc-600 hover:bg-zinc-50 transition-colors"
          title={`${pendingCount} pending approval${pendingCount !== 1 ? 's' : ''}`}
        >
          <Bell size={16} />
          {pendingCount > 0 && (
            <span className="absolute -top-0.5 -right-0.5 w-4 h-4 bg-rose-500 text-white text-[9px] font-bold rounded-full flex items-center justify-center leading-none">
              {pendingCount > 9 ? '9+' : pendingCount}
            </span>
          )}
        </Link>
      </div>
    </header>
  );
}
