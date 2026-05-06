import { useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { useUiMode } from '../../context/UiModeContext.jsx';
import GlobalLoadingBar from '../ui/GlobalLoadingBar.jsx';
import Sidebar from './Sidebar.jsx';
import TopBar from './TopBar.jsx';
import WorkflowStepper from '../WorkflowStepper.jsx';
import PixelSidebar from '../pixel/PixelSidebar.jsx';
import { ROUTE_META } from '../../router.jsx';
import { API } from '../../api.js';

export default function AppLayout() {
  const { mode } = useUiMode();
  const location = useLocation();
  const navigate = useNavigate();
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
    const [agent, plm, pim, ingestion] = await Promise.all([
      check('agent'), check('plm'), check('pim'), check('ingestion'),
    ]);
    setServices({ agent, plm, pim, ingestion });
  }

  const meta = ROUTE_META[location.pathname] ?? ROUTE_META['/requirements'];

  // Compatibility shim: map pathname back to legacy page ID for PixelSidebar
  const currentPage = location.pathname.replace(/^\//, '') || 'requirements';
  const onNavigate = (id) => navigate(`/${id}`);

  return (
    <>
      <GlobalLoadingBar />
      <Toaster position="top-right" richColors closeButton />
      <div
        className="flex h-screen overflow-hidden"
        style={mode === 'pixel' ? { background: 'var(--pixel-bg)' } : { background: '#f8fafc' }}
      >
        {mode === 'pixel' ? (
          <PixelSidebar currentPage={currentPage} onNavigate={onNavigate} services={services} />
        ) : (
          <Sidebar services={services} />
        )}

        <div className="flex flex-col flex-1 overflow-hidden">
          {!meta.hideTopBar && <TopBar title={meta.title} subtitle={meta.subtitle} />}

          {meta.step !== null && !meta.hideTopBar && mode !== 'pixel' && (
            <WorkflowStepper activeStep={meta.step} />
          )}

          <main key={location.pathname} className="flex-1 overflow-y-auto p-6 animate-fade-in">
            <Outlet />
          </main>
        </div>
      </div>
    </>
  );
}
