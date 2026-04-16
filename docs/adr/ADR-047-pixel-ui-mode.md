# ADR-047 — Pixel UI Mode: 8-bit RPG Gamified Dual UI System

| Field | Value |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-04-16 |
| **Author** | Solution Architecture Team |
| **Supersedes** | — |
| **Related** | ADR-046 (LLM Multi-Profile Routing) |

---

## Context

The Integration Mate dashboard is a technically functional but visually utilitarian tool. Stakeholder demos and internal PoC reviews benefit from a more engaging presentation mode that communicates the agentic, pipeline-driven nature of the system in a memorable way.

A "Pixel UI Mode" — an 8-bit RPG aesthetic layered over the existing React app — achieves this without affecting the production code path (Classic mode remains the default). The feature is purely cosmetic and frontend-only: no backend API changes, no new data structures.

---

## Decision

Add a dual UI system controlled by a `UiModeContext` React context persisted to `localStorage`. When `mode === "pixel"`:

- A dark, retro RPG design system activates via a `.pixel-mode` root class.
- Navigation switches to `PixelSidebar` (same nav links, pixel styling).
- The Agent Workspace page swaps to `PixelAgentWorkspace`: RPG pipeline visualization + persona-narrated quest log.
- All other pages inherit the `.pixel-mode` CSS without component changes.

When `mode === "classic"`, all pixel code paths are bypassed completely.

---

## Agent Persona Mapping

| Pipeline Stage | RPG Persona | Idle | Working | Success | Error |
|---|---|---|---|---|---|
| ingestion  | Archivist | 📜 | 📖 | 🗝️ | 💀 |
| retrieval  | Librarian | 🔍 | 🔎 | 📚 | ❌ |
| generation | Writer    | ✍️ | 📝 | 📄 | 💔 |
| qa         | Guardian  | 🛡️ | ⚔️ | ✅ | 🚫 |
| enrichment | Mage      | 🔮 | ✨ | ⭐ | 💥 |

---

## Architecture

```
src/
  context/
    UiModeContext.jsx          ← Provider + useUiMode hook (localStorage)
  components/
    pixel/
      personas.js              ← AGENT_PERSONAS, PERSONA_EMOJI, inferStageFromLog()
      Sprite.jsx               ← Emoji sprite with CSS keyframe animations
      PipelineView.jsx         ← Horizontal 5-stage RPG pipeline visualization
      PersonaNarrator.js       ← narrateLog(): regex patterns → RPG narration text
      PixelAgentWorkspace.jsx  ← Full pixel workspace (reuses useAgentLogs hook)
      PixelDocumentView.jsx    ← Quest-scroll document renderer
      PixelSidebar.jsx         ← Pixel nav sidebar (same links, pixel style)
      UiModeToggle.jsx         ← Classic/Pixel toggle button (used in TopBar)
    layout/
      TopBar.jsx               ← +UiModeToggle in right section
  App.jsx                      ← UiModeProvider wrapper; conditional sidebar + page
```

### CSS Design System (`index.css` — `.pixel-mode`)

| Token | Value |
|---|---|
| `--pixel-bg` | `#0d0d0d` |
| `--pixel-surface` | `#1a1a2e` |
| `--pixel-primary` | `#4ade80` (green) |
| `--pixel-accent` | `#fbbf24` (amber) |
| `--pixel-danger` | `#f87171` (red) |
| `--pixel-font` | `'Press Start 2P', monospace` |

### Sprite Animation Classes

| Class | Animation | Trigger |
|---|---|---|
| `.pixel-working` | `pixel-blink` (0.8s) | Stage is active/running |
| `.pixel-success` | `pixel-glow` (1.5s) | Stage completed |
| `.pixel-error` | `pixel-shake` (0.4s) | Stage errored |

---

## Alternatives Considered

| Option | Rejected Reason |
|---|---|
| Separate pixel route (`/pixel`) | Would duplicate all page state management; mode switch mid-session would lose state |
| PNG sprite sheets | Would require AI image generation or external assets; emoji/CSS approach is self-contained |
| Full page re-style for all pages | Pixel mode would break Classic mode's Tailwind prose classes and MarkdownViewer |
| Backend-persisted UI mode | Over-engineering for a cosmetic preference; `localStorage` is appropriate scope |

---

## Consequences

**Positive:**
- Classic mode is completely unaffected — zero risk to production code path.
- Pixel components reuse all existing hooks (`useAgentLogs`, `useAgentStatus`) — no API duplication.
- `PersonaNarrator.js` is a pure function with no side effects — fully testable and maintainable.
- Press Start 2P loaded via Google Fonts — no bundle size impact for Classic mode users.

**Negative / Trade-offs:**
- `PixelAgentWorkspace` duplicates some layout from `AgentWorkspacePage` — acceptable given the cosmetic divergence.
- Press Start 2P renders text very small at normal font sizes — all pixel text uses fixed tiny sizes (5–13px).
- `UiModeProvider` wraps the entire app, so `useUiMode()` can only be called inside components rendered inside the provider.

---

## Validation Plan

- [ ] Toggle Classic → Pixel → Classic: UI mode persists across page refresh (localStorage)
- [ ] All 5 nav groups navigate correctly in PixelSidebar
- [ ] Agent Workspace shows PipelineView + narrated quest log in pixel mode
- [ ] Pipeline stage indicators update as log messages arrive
- [ ] TopBar UiModeToggle visible and functional in both modes
- [ ] Classic mode: no visual regression (Tailwind styles unaffected)

---

## Rollback Strategy

Remove `UiModeProvider` from `App.jsx` and the two conditional branches (sidebar/page). All pixel components are isolated in `src/components/pixel/` — they can be removed without affecting any other code. The CSS block in `index.css` is clearly delimited and can be deleted in one cut.

---

## Files Changed

| File | Change |
|---|---|
| `services/web-dashboard/index.html` | Add Press Start 2P to Google Fonts URL |
| `services/web-dashboard/src/index.css` | Append pixel CSS design system |
| `services/web-dashboard/src/context/UiModeContext.jsx` | New — UiModeProvider + useUiMode |
| `services/web-dashboard/src/components/pixel/UiModeToggle.jsx` | New |
| `services/web-dashboard/src/components/pixel/personas.js` | New |
| `services/web-dashboard/src/components/pixel/Sprite.jsx` | New |
| `services/web-dashboard/src/components/pixel/PipelineView.jsx` | New |
| `services/web-dashboard/src/components/pixel/PersonaNarrator.js` | New |
| `services/web-dashboard/src/components/pixel/PixelAgentWorkspace.jsx` | New |
| `services/web-dashboard/src/components/pixel/PixelDocumentView.jsx` | New |
| `services/web-dashboard/src/components/pixel/PixelSidebar.jsx` | New |
| `services/web-dashboard/src/App.jsx` | Add UiModeProvider, conditional sidebar/page |
| `services/web-dashboard/src/components/layout/TopBar.jsx` | Add UiModeToggle |
