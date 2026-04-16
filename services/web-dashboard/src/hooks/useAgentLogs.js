/**
 * useAgentLogs — TanStack Query hook for agent log polling.
 * R2: Replaces manual setInterval + useState in AgentWorkspacePage.
 * Polls every 3s while agent is running; slows to 15s when idle.
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { API } from '../api';

const LOGS_KEY = ['agent', 'logs'];

async function fetchLogs() {
  const res = await API.agent.logs(0);
  if (!res.ok) throw new Error(`Failed to fetch logs (${res.status})`);
  const data = await res.json();
  return { logs: data.logs || [], running: !data.finished, progress: data.progress ?? {} };
}

export function useAgentLogs() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: LOGS_KEY,
    queryFn: fetchLogs,
    refetchInterval: (query) => {
      // Poll fast while running, slow when idle
      return query.state.data?.running ? 3_000 : 15_000;
    },
  });

  const triggerMutation = useMutation({
    mutationFn: ({ pinnedDocIds = [], llmProfile = 'default' } = {}) =>
      API.agent.trigger(pinnedDocIds, llmProfile),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: LOGS_KEY }),
  });

  const cancelMutation = useMutation({
    mutationFn: () => API.agent.cancel(),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: LOGS_KEY }),
  });

  return {
    logs: query.data?.logs ?? [],
    isRunning: query.data?.running ?? false,
    progress: query.data?.progress ?? {},
    isLoading: query.isLoading,
    error: query.error?.message ?? null,
    trigger: triggerMutation.mutate,
    cancel: cancelMutation.mutate,
    isTriggering: triggerMutation.isPending,
    isCancelling: cancelMutation.isPending,
    triggerError: triggerMutation.error?.message ?? null,
  };
}
