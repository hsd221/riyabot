# RiyaBot Console

RiyaBot Console 是 RiyaBot 的 Web 管理面板，基于 React 19、TypeScript、Vite 和 Tailwind CSS 构建，由后端 `src/webui/` 的 FastAPI 服务提供接口和静态资源。

## 功能范围

- 仪表盘：查看请求量、Token、费用和模型使用情况。
- 配置管理：编辑 bot、模型厂商、模型分配和适配器配置。
- 本地聊天：通过 WebSocket 直接与当前 bot 实例对话。
- 实时日志：查看、过滤和导出后端日志。
- 插件管理：浏览、安装、卸载和更新插件。
- 资源管理：维护表情包、表达方式和知识图谱。
- 人物关系：查看和编辑已知用户信息。
- 系统设置：主题、动画、认证 Token 和版本信息。

## 开发

```bash
bun install
bun run dev
```

开发服务器默认运行在 `7999`，并通过 Vite proxy 访问后端 API。

## 构建

```bash
bun run build
```

构建产物输出到 `dist/`，由 RiyaBot 后端静态服务读取。Docker 构建前请先执行该命令，否则镜像中的 WebUI 可能缺失或过期。

## 项目结构

```text
webui/
├── src/
│   ├── components/          # 通用组件与布局
│   ├── routes/              # TanStack Router 页面
│   ├── lib/                 # API 客户端、WebSocket、工具函数
│   ├── hooks/               # React hooks
│   ├── store/               # Jotai 状态
│   ├── types/               # TypeScript 类型
│   ├── router.tsx           # 路由配置
│   └── main.tsx             # 应用入口
├── public/                  # 静态资源
├── vite.config.ts           # Vite 配置
├── tailwind.config.js       # Tailwind 配置
└── package.json             # Bun 项目配置
```

## 维护注意

- WebUI API 路由必须在后端静态文件挂载前注册。
- 配置表单由后端 dataclass schema 驱动，新增配置字段时要同时检查 schema 输出。
- `dist/` 是构建产物，不应手写维护。
- WebUI 文案中的 bot 昵称不一定等同于项目名，运行时角色名应由配置决定。
