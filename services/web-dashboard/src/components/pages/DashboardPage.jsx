import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate } from 'react-router-dom';
import {
  ArrowRight, FileText, CheckCircle, Library, Clock,
  Activity, Zap, AlertCircle,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useProject } from '../../context/ProjectContext.jsx';
import { API } from '../../api.js';
import { staggerContainer, staggerItem, fadeUp } from '../ui/motion.js';

function StatCard({ label, value, icon: Icon, href, color, bg, isLoading }) {
  return (
    <Link
      to={href}
      className="bg-white rounded-xl border border-zinc-200 p-5 hover:border-zinc-300 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-zinc-500 font-medium mb-1">{label}</p>
          {isLoading ? (
            <div className="h-8 w-12 bg-zinc-100 rounded animate-pulse mt-1" />
          ) : (
            <p className="text-3xl font-semibold text-zinc-900" style={{ fontFamily: 'Outfit, sans-serif' }}>
              {value}
            </p>
          )}
        </div>
        <div className={`w-9 h-9 ${bg} rounded-lg flex items-center justify-center flex-shrink-0`}>
          <Icon size={18} className={color} />
        </div>
      </div>
    </Link>
  );
}

export default function DashboardPage() {
  const { activeProjectId, projects } = useProject();
  const navigate = useNavigate();
  const activeProject = projects.find(p => p.prefix === activeProjectId);

  const { data: requirements = [], isLoading: loadingReqs } = useQuery({
    queryKey: ['requirements'],
    queryFn: async () => {
      const res = await API.requirements.list();
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : (data.requirements ?? []);
    },
  });

  const { data: pendingApprovals = [], isLoading: loadingApprovals } = useQuery({
    queryKey: ['approvals', 'pending'],
    queryFn: async () => {
      const res = await API.approvals.pending();
      if (!res.ok) return [];
      const data = await res.json();
      return Array.isArray(data) ? data : [];
    },
    refetchInterval: 15000,
  });

  const { data: kbStats, isLoading: loadingKb } = useQuery({
    queryKey: ['kb', 'stats'],
    queryFn: async () => {
      const res = await API.kb.stats();
      if (!res.ok) return null;
      return res.json();
    },
  });

  const { data: agentData, isLoading: loadingAgent } = useQuery({
    queryKey: ['agent', 'logs'],
    queryFn: async () => {
      const res = await API.agent.logs(0);
      if (!res.ok) return null;
      return res.json();
    },
    refetchInterval: 15000,
  });

  const kbDocCount = kbStats?.total_documents ?? kbStats?.count ?? kbStats?.total ?? '—';
  const lastRunLabel = (() => {
    const logs = agentData?.logs ?? [];
    if (agentData?.running) return 'Running…';
    if (logs.length === 0) return 'Never';
    const last = logs[logs.length - 1];
    return last?.timestamp ?? last?.ts ?? 'Recent';
  })();

  const nextStep = (() => {
    if (agentData?.running) return { label: 'Agent is running — view progress', href: '/agent' };
    if (pendingApprovals.length > 0) return { label: `Review ${pendingApprovals.length} pending approval${pendingApprovals.length !== 1 ? 's' : ''}`, href: '/approvals' };
    if (requirements.length > 0) return { label: 'Run agent on uploaded requirements', href: '/agent' };
    return { label: 'Upload requirements to get started', href: '/requirements' };
  })();

  const recentLogs = (agentData?.logs ?? []).slice(-5).reverse();

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div>
        <h1
          className="text-2xl font-semibold text-zinc-900"
          style={{ fontFamily: 'Outfit, sans-serif' }}
        >
          {activeProject
            ? `${activeProject.client_name} (${activeProject.prefix})`
            : 'All Projects'}
        </h1>
        <p className="text-zinc-500 text-sm mt-1">
          {activeProject?.description ?? 'Select a project from the toolbar to filter by project.'}
        </p>
      </div>

      {/* Stat cards */}
      <motion.div
        className="grid grid-cols-4 gap-4"
        variants={staggerContainer}
        initial="hidden"
        animate="show"
      >
        {[
          { label: 'Requirements',    value: requirements.length,     icon: FileText,    href: '/requirements', color: 'text-sky-600',     bg: 'bg-sky-50',     isLoading: loadingReqs      },
          { label: 'Pending Approvals', value: pendingApprovals.length, icon: AlertCircle, href: '/approvals',    color: 'text-amber-600',   bg: 'bg-amber-50',   isLoading: loadingApprovals },
          { label: 'KB Documents',    value: kbDocCount,              icon: Library,     href: '/kb',           color: 'text-emerald-600', bg: 'bg-emerald-50', isLoading: loadingKb        },
          { label: 'Last Agent Run',  value: lastRunLabel,            icon: Clock,       href: '/agent',        color: 'text-violet-600',  bg: 'bg-violet-50',  isLoading: loadingAgent     },
        ].map(card => (
          <motion.div key={card.label} variants={staggerItem}>
            <StatCard {...card} />
          </motion.div>
        ))}
      </motion.div>

      {/* Continue Workflow CTA */}
      <motion.div
        variants={fadeUp}
        initial="hidden"
        animate="show"
        className="bg-sky-600 rounded-xl p-6 flex items-center justify-between"
      >
        <div>
          <div className="flex items-center gap-2 mb-1">
            <Zap size={15} className="text-sky-200" />
            <p className="text-sky-100 text-xs font-medium uppercase tracking-wide">
              Continue Workflow
            </p>
          </div>
          <p className="text-white text-lg font-semibold" style={{ fontFamily: 'Outfit, sans-serif' }}>
            {nextStep.label}
          </p>
        </div>
        <button
          onClick={() => navigate(nextStep.href)}
          className="flex items-center gap-2 px-5 py-2.5 bg-white text-sky-700 font-semibold text-sm rounded-lg hover:bg-sky-50 transition-colors flex-shrink-0"
        >
          Go
          <ArrowRight size={15} />
        </button>
      </motion.div>

      {/* Recent Activity */}
      <div className="bg-white rounded-xl border border-zinc-200 overflow-hidden">
        <div className="px-5 py-4 border-b border-zinc-100 flex items-center gap-2">
          <Activity size={15} className="text-zinc-400" />
          <h2
            className="text-sm font-semibold text-zinc-700"
            style={{ fontFamily: 'Outfit, sans-serif' }}
          >
            Recent Agent Activity
          </h2>
          {agentData?.running && (
            <span className="ml-auto flex items-center gap-1.5 text-xs text-sky-600 font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-sky-500 animate-pulse" />
              Running
            </span>
          )}
        </div>

        {loadingAgent ? (
          <div className="px-5 py-6 space-y-3">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-4 bg-zinc-100 rounded animate-pulse" />
            ))}
          </div>
        ) : recentLogs.length === 0 ? (
          <div className="px-5 py-10 text-center">
            <CheckCircle size={28} className="text-zinc-200 mx-auto mb-3" />
            <p className="text-zinc-400 text-sm">No agent runs yet.</p>
            <Link to="/requirements" className="text-sky-600 text-sm hover:underline mt-1 inline-block">
              Upload requirements to get started →
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-zinc-50">
            {recentLogs.map((log, i) => (
              <div key={i} className="px-5 py-3 flex items-start gap-3">
                <span className="text-zinc-300 text-xs font-mono mt-0.5 flex-shrink-0 w-20 truncate">
                  {log.timestamp ?? log.ts ?? '—'}
                </span>
                <span className="text-zinc-600 text-sm leading-relaxed">
                  {log.message ?? log.msg ?? JSON.stringify(log)}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
