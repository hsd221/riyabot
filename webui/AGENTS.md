# webui - React Dashboard

## Scope and Stack
`webui/` is the React 19 and TypeScript dashboard built with Vite, Tailwind CSS, TanStack Router, Radix/shadcn primitives, and Bun. Production output goes to `dist/` and is served by `src/webui/webui_server.py`; never hand-edit build artifacts.

## Source Map
- `src/main.tsx`: provider stack, global error boundary, router, tour, and toast setup.
- `src/router.tsx`: explicit route tree, protected layout, and authentication redirects.
- `src/routes/`: pages for setup, authentication, configuration, resources, plugins, chat, logs, statistics, settings, and surveys.
- `src/components/ui/`: shared UI primitives; extend these before creating one-off controls.
- `src/components/layout.tsx`: authenticated application shell and navigation.
- `src/lib/*-api.ts` and `src/lib/api/`: domain API clients and response mapping.
- `src/lib/fetch-with-auth.ts`: canonical authenticated HTTP wrapper.
- `src/lib/log-websocket.ts` and `src/lib/log-stream.ts`: log streaming and reconnection.
- `src/hooks/`, `src/types/`, and `src/config/`: reusable hooks, API types, and survey configuration.

## Data, Auth, and Routing Contracts
Use relative `/api/...` URLs through `fetchWithAuth()` so HttpOnly cookies are included and a backend `401` consistently redirects to `/auth`. Do not create hard-coded localhost API clients or persist credentials in `localStorage`. Auth and setup redirects belong in the TanStack route guard and existing auth hook. WebSockets obtain a one-use token from `/api/webui/ws-token`; reuse the existing managers rather than opening unauthenticated sockets.

Keep domain request/response types near `src/types/` or the owning API module. Configuration forms are driven by backend schemas and save by section; preserve the existing `useAutoSave`, `useConfigAutoSave`, and model auto-save hooks instead of adding a parallel global store. Read displayed dashboard version data from `src/lib/version.ts`; do not hard-code backend or legacy product versions in components.

## UI Conventions
Use typed function components and existing Radix/shadcn components, Tailwind utilities, Lucide icons, toasts, error boundaries, and loading states. Match the dense dashboard layout and responsive behavior already present. Keep API calls out of generic UI primitives. Maintain keyboard access, visible focus, semantic labels, and reduced-motion behavior.

## Commands and Verification

```bash
bun run dev       # Vite on :7999; /api proxies to :8001
bun test          # Bun tests under webui/tests/
bun run lint      # ESLint and React Hooks rules
bun run format    # Prettier for source files
bun run build     # TypeScript check and production bundle
```

For UI changes, verify both narrow mobile and desktop layouts and include screenshots in the PR.
