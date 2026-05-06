import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { LoadingProvider } from './context/LoadingContext.jsx';
import { UiModeProvider } from './context/UiModeContext.jsx';
import { ProjectProvider } from './context/ProjectContext.jsx';
import { router } from './router.jsx';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <UiModeProvider>
        <ProjectProvider>
          <LoadingProvider>
            <RouterProvider router={router} />
          </LoadingProvider>
        </ProjectProvider>
      </UiModeProvider>
    </QueryClientProvider>
  );
}
