import { useState, useEffect } from 'react';
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
import { API } from './api.js';

const PAGE_META = {
  requirements: { title: 'Requirements', subtitle: 'Upload and manage integration requirements', step: 1 },
  kb: { title: 'Knowledge Base', subtitle: 'Best practices document library', step: 2 },
  apis: { title: 'API Systems', subtitle: 'Connected source and target systems', step: null },
  agent: { title: 'Agent Workspace', subtitle: 'AI-powered document generation', step: 3 },
  catalog: { title: 'Integration Catalog', subtitle: 'Browse generated integrations', step: 5 },
  documents: { title: 'Generated Docs', subtitle: 'View functional and technical specifications', step: 5 },
  approvals: { title: 'HITL Approvals', subtitle: 'Human-in-the-loop document review', step: 4 },
  reset: { title: 'Reset Tools', subtitle: 'Admin data management', step: null },
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
    default: return <RequirementsPage />;
  }
}

export default function App() {
  const [currentPage, setCurrentPage] = useState('requirements');
  const [services, setServices] = useState({ agent: null, plm: null, pim: null });

  useEffect(() => {
    checkServices();
    const interval = setInterval(checkServices, 15000);
    return () => clearInterval(interval);
  }, []);

  async function checkServices() {
    const check = async (port) => {
      try {
        const res = await API.health.check(port);
        return res.ok ? 'ok' : 'error';
      } catch {
        return 'error';
      }
    };
    const [agent, plm, pim] = await Promise.all([check(4003), check(3001), check(3002)]);
    setServices({ agent, plm, pim });
  }

  const meta = PAGE_META[currentPage] ?? PAGE_META.requirements;

  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      <Sidebar currentPage={currentPage} onNavigate={setCurrentPage} services={services} />

      <div className="flex flex-col flex-1 overflow-hidden">
        <TopBar title={meta.title} subtitle={meta.subtitle} />

        {meta.step !== null && <WorkflowStepper activeStep={meta.step} />}

        <main
          key={currentPage}
          className="flex-1 overflow-y-auto p-6 animate-fade-in"
        >
          {renderPage(currentPage)}
        </main>
      </div>
    </div>
  );
}
