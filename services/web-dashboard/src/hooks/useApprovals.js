/**
 * useApprovals — TanStack Query hook for HITL approval state management.
 * R2/R5: Replaces manual useState + loadApprovals() + inline handlers in ApprovalsPage.
 *
 * Provides:
 *  - approvals: list of pending approvals (auto-polled every 15s)
 *  - approve / reject / regenerate: async mutations with automatic cache invalidation
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { API } from '../api';

const PENDING_KEY = ['approvals', 'pending'];

async function fetchPending() {
  const res = await API.approvals.pending();
  if (!res.ok) throw new Error(`Failed to load approvals (${res.status})`);
  const data = await res.json();
  return data.data ?? [];
}

export function useApprovals() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: PENDING_KEY,
    queryFn: fetchPending,
    refetchInterval: 15_000,  // poll for new pending approvals every 15s
  });

  const approveMutation = useMutation({
    mutationFn: ({ id, content }) => API.approvals.approve(id, content),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PENDING_KEY }),
  });

  const rejectMutation = useMutation({
    mutationFn: ({ id, feedback }) => API.approvals.reject(id, feedback),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PENDING_KEY }),
  });

  const regenerateMutation = useMutation({
    mutationFn: ({ id }) => API.approvals.regenerate(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: PENDING_KEY }),
  });

  return {
    // Data
    approvals: query.data ?? [],
    isLoading: query.isLoading,
    loadError: query.error?.message ?? null,

    // Approve
    approve: approveMutation.mutate,
    isApproving: approveMutation.isPending,
    approveError: approveMutation.error?.message ?? null,

    // Reject
    reject: rejectMutation.mutate,
    isRejecting: rejectMutation.isPending,
    rejectError: rejectMutation.error?.message ?? null,

    // Regenerate
    regenerate: regenerateMutation.mutate,
    isRegenerating: regenerateMutation.isPending,
    regenerateError: regenerateMutation.error?.message ?? null,
  };
}
