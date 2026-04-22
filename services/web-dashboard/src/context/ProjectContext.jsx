/**
 * ProjectContext — Global active project selection (ADR-050).
 *
 * Persists the active project prefix in localStorage under 'active_project_id'.
 * null means "All Projects" (no filter applied — backward-compatible).
 */
import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { API } from '../api.js';

const ProjectContext = createContext({
  activeProjectId: null,
  setActiveProjectId: () => {},
  projects: [],
  refreshProjects: async () => {},
});

export function ProjectProvider({ children }) {
  const [activeProjectId, setActiveProjectIdState] = useState(
    () => localStorage.getItem('active_project_id') || null,
  );
  const [projects, setProjects] = useState([]);

  const refreshProjects = useCallback(async () => {
    try {
      const res = await API.projects.list();
      const data = await res.json();
      setProjects(data.data || []);
    } catch {
      // silently tolerate — backend may be starting up
    }
  }, []);

  useEffect(() => { refreshProjects(); }, [refreshProjects]);

  const setActiveProjectId = (id) => {
    setActiveProjectIdState(id);
    if (id) localStorage.setItem('active_project_id', id);
    else localStorage.removeItem('active_project_id');
  };

  return (
    <ProjectContext.Provider value={{ activeProjectId, setActiveProjectId, projects, refreshProjects }}>
      {children}
    </ProjectContext.Provider>
  );
}

export const useProject = () => useContext(ProjectContext);
