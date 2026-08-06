# 部署指南

本文介绍 RiyaBot 的生产部署方式，包括 Docker Compose 部署、跨主机/跨容器连接的令牌配置，以及运行时目录与端口说明。源码安装与首次配置见[安装与启动](installation.md)。

## 组件构成

一个完整的 RiyaBot 部署通常包含三部分：

- **核心（core）**：RiyaBot 本体，负责聊天行为、记忆、插件与 WebUI；
- **适配器（adapters）**：把 QQ 等平台的消息协议转换成 RiyaBot 使用的旧版消息协议；
- **协议端（如 NapCat）**：真正登录 QQ 账号、收发底层消息的客户端。

核心与适配器之间通过**旧版消息 WebSocket**通信，默认端口 `8000`（由 `.env` 的 `HOST` / `PORT` 控制）。

## 端口与环境变量

`.env` 由首次启动时依据 `template/template.env` 自动生成，常用项：

| 变量 | 默认 | 说明 |
|---|---|---|
| `HOST` | 127.0.0.1 | 旧版消息服务器监听地址 |
| `PORT` | 8000 | 旧版消息服务器端口（核心 ↔ 适配器） |
| `WEBUI_HOST` | 127.0.0.1 | WebUI 监听地址 |
| `WEBUI_PORT` | 8001 | WebUI 端口 |
| `MAIBOT_LEGACY_SERVER_TOKEN` | 空 | 跨主机/跨容器连接时，核心与适配器共享的强随机令牌 |
| `MAIBOT_ALLOW_UNAUTHENTICATED_LEGACY_SERVER` | 0 | 是否允许旧版消息服务器远程匿名监听（仅迁移用途，不推荐） |

> 更多可选安全开关（模型 URL、插件仓库、媒体 URL 等）见 `template/template.env` 中的注释，默认值均为安全侧，通常无需改动。

### 跨主机/跨容器连接的令牌

旧版消息 WebSocket 默认拒绝远程匿名监听。当核心与适配器不在同一进程/回环网络时，必须为二者配置**同一个**强随机令牌：

```bash
export MAIBOT_LEGACY_SERVER_TOKEN="$(openssl rand -hex 32)"
```

若适配器镜像尚不支持该变量，可临时保持令牌为空并设置 `MAIBOT_ALLOW_UNAUTHENTICATED_LEGACY_SERVER=1`。这仅适用于受信的私有网络，且**绝不能对外发布核心的 `8000` 端口**；适配器升级后应立即改用共享令牌并关闭该兼容开关。

## Docker 部署

### 构建镜像

Dockerfile 内置独立的 Bun 构建阶段来生成 WebUI 静态资源，无需在宿主机预先构建前端：

```bash
docker build -t riyabot .
```

### 使用 Compose

仓库根目录的 `docker-compose.yml` 提供了包含核心、适配器、NapCat 与可选 `sqlite-web` 调试面板的示例编排。核心服务的关键约定：

- **端口映射**：默认把容器内 `8001`（WebUI）映射到宿主机 `127.0.0.1:18001`，仅本机可访问。可用环境变量 `RIYABOT_WEBUI_BIND_ADDRESS` / `RIYABOT_WEBUI_PORT` 调整。
- **不发布 `8000`**：核心的旧版消息端口默认不对外发布；启用远程匿名兼容模式时更绝不能发布。
- **数据卷**：配置持久化在 `./docker-config/`，运行数据在 `./data/RiyaBot/`（含 `plugins/`、`logs/`）。
- **最小权限**：核心容器启用了 `no-new-privileges` 且 `cap_drop: ALL`。

配置共享令牌后启动：

```bash
export MAIBOT_LEGACY_SERVER_TOKEN="$(openssl rand -hex 32)"
docker compose up -d
```

调试用的 `sqlite-web`（只读挂载数据库）位于 `debug` profile，需要时显式启用：

```bash
docker compose --profile debug up -d
```

> 注意：Compose 使用容器内 `/RiyaBot` 与宿主机 `./data/RiyaBot` 作为默认路径。从旧部署迁移时，需要手动把旧数据目录复制到新路径。

## 运行时目录

以下目录属于运行时数据，不应提交到仓库：

- `config/` — 自动生成的 `bot_config.toml` / `model_config.toml`；
- `data/` — 数据库、记忆、表情等持久化数据；
- `logs/` — 日志文件。

## 程序更新

WebUI 的「系统设置 > 关于」可检查并切换更新频道：

- **正式版**：跟踪 `main` 分支可达的最新正式 SemVer 标签（不含预发布）；
- **开发版**：跟踪远端 `dev` 分支的完整提交 SHA。

切换频道只保存偏好，不会立即更新。源码安装在当前提交可识别、受跟踪文件无修改、目标为快进提交且 `git`、`uv`、`bun` 均可用时，可由 Runner 执行一键更新并重启；目标落后、分支分叉或检查变化时更新会被拒绝，不会强制重置或降级。

Docker 与压缩包安装支持在线检查，但不会在运行中的容器或安装目录内替换自身。Docker 部署发现新版本后，请拉取对应的 GHCR 镜像并重建容器。
