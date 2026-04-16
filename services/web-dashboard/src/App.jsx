import { useState, useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';
import { LoadingProvider } from './context/LoadingContext.jsx';
import { UiModeProvider, useUiMode } from './context/UiModeContext.jsx';
import GlobalLoadingBar from './components/ui/GlobalLoadingBar.jsx';
import Sidebar from './components/layout/Sidebar.jsx';
import TopBar from './components/layout/TopBar.jsx';
import WorkflowStepper from './components/WorkflowStepper.jsx';
import RequirementsPage from './components/pages/RequirementsPage.jsx';
import KnowledgeBasePage from './components/pages/KnowledgeBasePage.jsx';
import ApiSystemsPage from './components/pages/ApiSystemsPage.jsx';
import AgentWorkspacePage from './components/pages/AgentWorkspacePage.jsx';
import CatalogPage from './components/pages/CatalogPage.jsx';
import DocumentsPage from './components/pages/DocumentsPage.jsx';
import ApprovalsPage from './components/pages/ApprovalsPage.jsx';
import ResetPage from './components/pages/ResetPage.jsx';
import ProjectDocsPage from './components/pages/ProjectDocsPage.jsx';
import LlmSettingsPage from './components/pages/LlmSettingsPage.jsx';
import IngestionSourcesPage from './components/pages/IngestionSourcesPage.jsx';
import PixelSidebar from './components/pixel/PixelSidebar.jsx';
import PixelAgentWorkspace from './components/pixel/PixelAgentWorkspace.jsx';
import { API } from './api.js';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,           // 30s — data stays fresh for 30s before background refetch
      retry: 1,                    // retry once on failure
      refetchOnWindowFocus: true,  // refetch when user returns to tab
    },
  },
});

const PAGE_META = {
  requirements: { title: 'Requirements', subtitle: 'Upload and manage integration requirements', step: 1 },
  kb: { title: 'Knowledge Base', subtitle: 'Best practices document library', step: null, hideTopBar: true },
  apis: { title: 'API Systems', subtitle: 'Connected source and target systems', step: null },
  agent: { title: 'Agent Workspace', subtitle: 'AI-powered document generation', step: 3 },
  catalog: { title: 'Integration Catalog', subtitle: 'Browse generated integrations', step: 5 },
  documents: { title: 'Generated Docs', subtitle: 'View functional and technical specifications', step: 5 },
  approvals: { title: 'HITL Approvals', subtitle: 'Human-in-the-loop document review', step: 4 },
  reset: { title: 'Reset Tools', subtitle: 'Admin data management', step: null },
  'project-docs': { title: 'Project Docs', subtitle: 'Browse governance documents, ADRs, and checklists', step: null },
  'llm-settings':       { title: 'LLM Settings',       subtitle: 'Tune model parameters and test response times',                  step: null },
  'ingestion-sources':  { title: 'Ingestion Sources',  subtitle: 'Manage OpenAPI, HTML and MCP knowledge base sources',            step: null },
};

function renderPage(page) {
  switch (page) {
    case 'requirements': return <RequirementsPage />;
    case 'kb': return <KnowledgeBasePage />;
    case 'apis': return <ApiSystemsPage />;
    case 'agent': return <AgentWorkspacePage />;
    case 'catalog': return <CatalogPage />;
    case 'documents': return <DocumentsPage />;
    case 'approvals': return <ApprovalsPage />;
    case 'reset': return <ResetPage />;
    case 'project-docs': return <ProjectDocsPage />;
    case 'llm-settings':      return <LlmSettingsPage />;
    case 'ingestion-sources': return <IngestionSourcesPage />;
    default: return <RequirementsPage />;
  }
}

function AppInner() {
  const { mode } = useUiMode();
  const [currentPage, setCurrentPage] = useState('requirements');
  const [services, setServices] = useState({ agent: null, plm: null, pim: null, ingestion: null });

  useEffect(() => {
    checkServices();
    const interval = setInterval(checkServices, 15000);
    return () => clearInterval(interval);
  }, []);

  async function checkServices() {
    const check = async (service) => {
      try {
        const res = await API.health.check(service);
        return res.ok ? 'ok' : 'error';
      } catch {
        return 'error';
      }
    };
    const [agent, plm, pim, ingestion] = await Promise.all([check('agent'), check('plm'), check('pim'), check('ingestion')]);
    setServices({ agent, plm, pim, ingestion });
  }

  const meta = PAGE_META[currentPage] ?? PAGE_META.requirements;

  return (
    <>
      <GlobalLoadingBar />
      <Toaster position="top-right" richColors closeButton />
      <div className="flex h-screen overflow-hidden" style={mode === 'pixel' ? { background: 'var(--pixel-bg)' } : { background: '#f8fafc' }}>
        {mode === 'pixel' ? (
          <PixelSidebar currentPage={currentPage} onNavigate={setCurrentPage} services={services} />
        ) : (
          <Sidebar currentPage={currentPage} onNavigate={setCurrentPage} services={services} />
        )}

        <div className="flex flex-col flex-1 overflow-hidden">
          {!meta.hideTopBar && <TopBar title={meta.title} subtitle={meta.subtitle} />}

          {meta.step !== null && !meta.hideTopBar && mode !== 'pixel' && (
            <WorkflowStepper activeStep={meta.step} />
          )}

          <main key={currentPage} className="flex-1 overflow-y-auto p-6 animate-fade-in">
            {currentPage === 'agent' && mode === 'pixel' ? (
              <PixelAgentWorkspace />
            ) : (
              renderPage(currentPage)
            )}
          </main>
        </div>
      </div>
    </>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <UiModeProvider>
        <LoadingProvider>
          <AppInner />
        </LoadingProvider>
      </UiModeProvider>
    </QueryClientProvider>
  );
}
