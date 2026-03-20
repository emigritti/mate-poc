# ADR-033 — TanStack Query for Frontend Server-State Management

| Field        | Value                                                        |
|--------------|--------------------------------------------------------------|
| **Status**   | Accepted                                                     |
| **Date**     | 2026-03-20                                                   |
| **Tags**     | frontend, react-query, tanstack, hooks, state-management, phase3 |

## Context
All React pages in the web dashboard manage server data via independent `useState` + `useEffect` +
manual `fetch` calls. This pattern leads to:
- No caching: identical data is re-fetched on every page mount
- No background polling: pages go stale between navigations
- Duplicated error/loading state boilerplate in every component
- No request deduplication: two components fetching the same endpoint make two requests

## Decision
Install `@tanstack/react-query` v5 as the server-state management layer.

A `QueryClient` is created in `App.jsx` (with `staleTime: 30s`, `retry: 1`,
`refetchOnWindowFocus: true`) and provided via `QueryClientProvider` at the app root.

Two pilot custom hooks are introduced under `src/hooks/`:
- `useApprovals()` — `useQuery` for pending approvals + three `useMutation`s (approve, reject, regenerate)
- `useAgentLogs()` — `useQuery` with adaptive `refetchInterval` (3s when running, 15s when idle) + two `useMutation`s (trigger, cancel)

`ApprovalsPage.jsx` and `AgentWorkspacePage.jsx` are refactored to consume these hooks,
removing all `useState`/`useEffect`/manual fetch boilerplate for server data.

## Alternatives Considered
- **Zustand**: global client-side state store — appropriate for UI state, not server-state; does not provide caching or background sync
- **SWR**: similar to TanStack Query — fewer features (no mutation state, less flexible `refetchInterval`), smaller ecosystem
- **Redux Toolkit Query (RTK Query)**: full-featured but adds Redux as a dependency — too heavy for a single-service frontend PoC
- **Keep manual fetch**: zero new dependencies — does not scale; each new page repeats the same boilerplate

## Validation Plan
- Manual: `npm run build` passes without errors
- Manual: approvals page and agent workspace page render and poll correctly in dev server

## Rollback
Remove `@tanstack/react-query` from `package.json`. Revert `App.jsx` (remove `QueryClientProvider`). Revert `ApprovalsPage.jsx` and `AgentWorkspacePage.jsx` to manual fetch pattern.
