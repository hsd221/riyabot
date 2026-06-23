# webui/ — Frontend (React + Vite)

Standalone React 19 + TypeScript project. Built with bun → `dist/` served by `src/webui/webui_server.py`.

## STRUCTURE
```
webui/
├── src/
│   ├── main.tsx             # Entry: Provider stack (Theme, Animation, QueryClient, Router)
│   ├── router.tsx           # TanStack Router: 19 routes, auth-guarded (beforeLoad)
│   ├── components/
│   │   ├── ui/              # 34 shadcn/ui primitives (new-york style, Tailwind)
│   │   ├── layout.tsx       # Sidebar + topbar shell
│   │   ├── tour/            # react-joyride onboarding (6 files)
│   │   └── ...              # CodeEditor, search-dialog, error-boundary, etc.
│   ├── routes/
│   │   ├── index.tsx        # Dashboard (Recharts)
│   │   ├── config/bot.tsx   # Bot config: 13 sections + dual-mode (visual/TOML)
│   │   ├── config/bot/sections/  # 13 independent section components
│   │   ├── config/model/    # Model config + hooks + components
│   │   └── ...              # 19 routes total
│   ├── lib/
│   │   ├── api.ts           # axios instance (baseURL dev: localhost:8000)
│   │   ├── fetch-with-auth.ts  # fetch + credentials:'include', auto-redirect on 401
│   │   ├── config-api.ts    # Schema-driven config CRUD
│   │   ├── log-websocket.ts # LogWebSocketManager singleton (30s heartbeat)
│   │   ├── version.ts       # APP_VERSION = '0.11.7 Beta' (Dashboard version)
│   │   └── ...              # 21 lib modules (domain API clients)
│   ├── hooks/               # use-auth, use-toast, etc.
│   ├── types/               # 8 type definition modules
│   └── store/               # Jotai atoms
├── package.json             # bun project, Dashboard version 0.11.6
├── vite.config.ts           # 13 manualChunks, proxy :7999→:8001
└── tailwind.config.js       # shadcn new-york, base color slate
```

## WHERE TO LOOK
| Task | Location |
|------|----------|
| Add page/route | `src/router.tsx` (define) + `src/routes/` (implement) |
| Add API client | `src/lib/` — add domain module, follow `config-api.ts` pattern |
| Add shadcn component | `src/components/ui/` (run `npx shadcn-ui add <name>`) |
| Bot config section | `src/routes/config/bot/sections/` — add component, register in `bot.tsx` |
| Theme/styling | `src/components/theme-provider.tsx` + `tailwind.config.js` |
| Auth guard | `src/hooks/use-auth.ts` + `router.tsx` beforeLoad |
| Version display | `src/lib/version.ts` (Dashboard) — MaiBot backend version hardcoded in JS |
| WebSocket logs | `src/lib/log-websocket.ts` singleton |

## CONVENTIONS
- **Stack**: React 19 + TanStack Router 1.x + Jotai + Tailwind 3 + shadcn/ui + Recharts + ReactFlow.
- **Auth**: Cookie-based (HttpOnly), no token in JS. `fetchWithAuth()` auto-carries credentials.
- **Auto-save**: `useConfigAutoSave` + `useAutoSave` — 2s debounce, section-by-section PATCH.
- **Build**: `bun install && bun run build` → `dist/`. `dist/` gitignored.
- **Dev server**: `bun run dev` (port 7999, proxies API to :8001).

## NOTES
- **Version dual-track**: `lib/version.ts` = Dashboard (0.11.7 Beta); MaiBot backend (0.12.2) hardcoded in frontend JS; `package.json` version (0.11.6) = npm package only.
- **Config UI**: backend Python dataclass schema drives frontend form rendering via `/api/webui/config/schema/*`.
- **Source origin**: MaiBot-Dashboard `dev-0.12` branch, merged into main repo.
