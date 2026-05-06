import { createBrowserRouter, Navigate } from 'react-router-dom';
import AppShell from './components/layout/AppShell.jsx';
import DashboardPage from './components/pages/DashboardPage.jsx';
import RequirementsPage from './components/pages/RequirementsPage.jsx';
import KnowledgeBasePage from './components/pages/KnowledgeBasePage.jsx';
import ApiSystemsPage from './components/pages/ApiSystemsPage.jsx';
import AgentWorkspacePage from './components/pages/AgentWorkspacePage.jsx';
import PixelAgentWorkspace from './components/pixel/PixelAgentWorkspace.jsx';
import CatalogPage from './components/pages/CatalogPage.jsx';
import DocumentsPage from './components/pages/DocumentsPage.jsx';
import ApprovalsPage from './components/pages/ApprovalsPage.jsx';
import ResetPage from './components/pages/ResetPage.jsx';
import ProjectDocsPage from './components/pages/ProjectDocsPage.jsx';
import LlmSettingsPage from './components/pages/LlmSettingsPage.jsx';
import AgentSettingsPage from './components/pages/AgentSettingsPage.jsx';
import IngestionSourcesPage from './components/pages/IngestionSourcesPage.jsx';
import WikiPage from './components/pages/WikiPage.jsx';
import EvalPage from './components/pages/EvalPage.jsx';
import { useUiMode } from './context/UiModeContext.jsx';

export const ROUTE_META = {
  '/dashboard':        { title: 'Dashboard',           subtitle: 'Project overview and quick actions',                             step: null },
  '/requirements':     { title: 'Requirements',         subtitle: 'Upload and manage integration requirements',                    step: 1    },
  '/kb':               { title: 'Knowledge Base',       subtitle: 'Best practices document library',                              step: null, hideTopBar: true },
  '/apis':             { title: 'API Systems',          subtitle: 'Connected source and target systems',                          step: null },
  '/agent':            { title: 'Agent Workspace',      subtitle: 'AI-powered document generation',                               step: 3    },
  '/catalog':          { title: 'Integration Catalog',  subtitle: 'Browse generated integrations',                                step: 5    },
  '/documents':        { title: 'Generated Docs',       subtitle: 'View functional and technical specifications',                  step: 5    },
  '/approvals':        { title: 'HITL Approvals',       subtitle: 'Human-in-the-loop document review',                            step: 4    },
  '/reset':            { title: 'Reset Tools',          subtitle: 'Admin data management',                                        step: null },
  '/project-docs':     { title: 'Project Docs',         subtitle: 'Browse governance documents, ADRs, and checklists',            step: null },
  '/llm-settings':     { title: 'LLM Settings',         subtitle: 'Tune model parameters and test response times',                step: null },
  '/agent-settings':   { title: 'Agent Settings',       subtitle: 'Quality gate, RAG, FactPack, vision and KB chunking',          step: null },
  '/ingestion-sources':{ title: 'Ingestion Sources',    subtitle: 'Manage OpenAPI, HTML and MCP knowledge base sources',          step: null },
  '/wiki':             { title: 'LLM Wiki',             subtitle: 'Knowledge graph — entities, relationships and Graph RAG',      step: null, hideTopBar: true },
  '/eval':             { title: 'RAG Eval Harness',     subtitle: 'Measure recall@5, MRR, NDCG@5 across pipeline versions',      step: null },
};

function AgentRoute() {
  const { mode } = useUiMode();
  return mode === 'pixel' ? <PixelAgentWorkspace /> : <AgentWorkspacePage />;
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true,               element: <Navigate to="/dashboard" replace /> },
      { path: 'dashboard',         element: <DashboardPage /> },
      { path: 'requirements',      element: <RequirementsPage /> },
      { path: 'kb',                element: <KnowledgeBasePage /> },
      { path: 'apis',              element: <ApiSystemsPage /> },
      { path: 'agent',             element: <AgentRoute /> },
      { path: 'catalog',           element: <CatalogPage /> },
      { path: 'documents',         element: <DocumentsPage /> },
      { path: 'approvals',         element: <ApprovalsPage /> },
      { path: 'reset',             element: <ResetPage /> },
      { path: 'project-docs',      element: <ProjectDocsPage /> },
      { path: 'llm-settings',      element: <LlmSettingsPage /> },
      { path: 'agent-settings',    element: <AgentSettingsPage /> },
      { path: 'ingestion-sources', element: <IngestionSourcesPage /> },
      { path: 'wiki',              element: <WikiPage /> },
      { path: 'eval',              element: <EvalPage /> },
    ],
  },
]);
