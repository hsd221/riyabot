<div align="center">
  <h1>RiyaBot <sub><small>璃夜Bot</small></sub></h1>
  <p>一个面向 QQ 群聊的拟生命体聊天机器人，基于大语言模型、长期记忆、行为规划和插件系统构建。</p>

  <p>
    <img src="https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white" alt="Python 3.10+">
    <img src="https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white" alt="React 19">
    <img src="https://img.shields.io/badge/FastAPI-WebUI-009688?logo=fastapi&logoColor=white" alt="FastAPI WebUI">
    <img src="https://img.shields.io/badge/License-GPL--3.0-blue" alt="GPL-3.0">
  </p>
</div>

## 介绍

RiyaBot 不是一个只等命令的工具型 bot。它更像一个会长期停留在群聊里的虚拟角色：观察上下文、决定什么时候说话、学习群友表达、使用表情和插件，并在持续互动中形成自己的记忆与行为习惯。

这个仓库基于 MaiBot/MaiCore fork 后继续改造，当前目标是把它整理成一个有独立命名、独立文档和更清晰维护边界的项目。

## 核心能力

- **群聊行为规划**：根据聊天上下文决定回复、等待、使用动作或插件。
- **长期记忆与人物关系**：记录用户、群聊、表达方式和知识片段，用于后续交互。
- **拟人化表达**：通过 Prompt、情绪、表情包和表达学习生成更自然的回复。
- **插件系统**：支持 Action、Command、Tool、Event 等扩展组件。
- **Web 管理面板**：提供配置、日志、插件、资源、人物关系和本地聊天管理。
- **适配器部署**：默认面向 QQ/NapCat 等 bot 协议适配场景。

## 快速开始

### 安装依赖

```bash
uv sync
```

### 准备配置

首次启动会根据 `src/config/` 中的 Python 配置定义自动生成 `config/bot_config.toml` 和
`config/model_config.toml`，无需手工复制核心 TOML 模板。初始模型配置不会预置厂商、模型或密钥，请在
WebUI 首次配置向导中填写 bot 信息并完成模型管理与任务分配。`config/`、`data/`、`logs/` 属于运行时目录，
不应该提交到仓库。

### 启动后端

```bash
python bot.py
```

首次启动可能需要确认 EULA 和隐私协议；首次配置完成前只会启动 WebUI。

### 启动 WebUI

```bash
cd webui
bun install
bun run dev
```

构建生产静态资源：

```bash
cd webui
bun run build
```

## Docker

构建 Docker 镜像前请先构建 WebUI 静态资源：

```bash
cd webui && bun install && bun run build
cd ..
docker build -t riyabot .
```

Compose 中的旧版消息 WebSocket 跨容器通信默认拒绝远程匿名监听。若适配器版本支持
`MAIBOT_LEGACY_SERVER_TOKEN`，请先为核心与适配器设置同一个强随机令牌：

```bash
export MAIBOT_LEGACY_SERVER_TOKEN="$(openssl rand -hex 32)"
docker compose up -d
```

若迁移中的旧适配器镜像尚不支持该变量，可暂时保持令牌为空并设置
`MAIBOT_ALLOW_UNAUTHENTICATED_LEGACY_SERVER=1`。此兼容方式仅适用于受信的私有 Compose 网络，且绝不能发布
核心的 `8000` 端口；完成适配器升级后应立即改用共享令牌并关闭兼容开关。

```bash
export MAIBOT_LEGACY_SERVER_TOKEN=
export MAIBOT_ALLOW_UNAUTHENTICATED_LEGACY_SERVER=1
docker compose up -d
```

注意：当前 compose 使用容器内 `/RiyaBot` 和宿主机 `data/RiyaBot` 作为默认路径。若你从旧部署迁移，需要手动把旧数据目录复制到新路径。

## 项目结构

```text
.
├── bot.py                  # Runner/Worker 入口
├── src/                    # Python 后端
│   ├── chat/               # 群聊/私聊行为、回复生成、规划逻辑
│   ├── plugin_system/      # 插件 SDK 与组件注册
│   ├── common/             # 日志、数据库、Prompt、基础设施
│   ├── config/             # TOML 配置定义、生成与升级
│   └── webui/              # FastAPI WebUI 后端
├── webui/                  # React 19 + Vite 管理面板
├── prompts/                # 外部 Prompt 模板
├── plugins/                # 外部插件目录
├── template/               # .env 启动环境模板
├── docs-src/               # 文档源文件
└── docker-compose.yml      # 容器化部署示例
```

## 开发命令

```bash
ruff check --fix .
ruff format .
```

消息流模拟：

```bash
MAIBOT_WORKER_PROCESS=1 uv run python tests/simulator.py --file tests/data/chat_exports/chat_histories_1.json
```

短 E2E：

```bash
uv run python tests/run_e2e.py --quick
```

## 贡献

这个 fork 目前优先整理自身定位、部署体验和稳定性。提交 PR 前请说明：

- 这次修改解决的问题或行为变化
- 是否影响配置、数据目录、插件 API 或部署方式
- 已经运行过的验证命令
- WebUI 相关修改的截图或录屏

新增功能建议先通过 Issue 讨论，避免和现有架构方向冲突。

## 来源与许可

RiyaBot fork 自 MaiBot/MaiCore，并继续遵循原项目的 GPL-3.0 开源许可。原项目作者、维护者和贡献者的工作构成了这个项目的基础。

使用前请阅读 [EULA](EULA.md) 和 [隐私协议](PRIVACY.md)。QQ bot、AI 生成内容和第三方模型服务都有各自的使用风险，请按平台规则和当地法律法规谨慎部署。
