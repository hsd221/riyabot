# 源码安装

源码安装适合需要修改 RiyaBot、开发插件或参与 WebUI 开发的场景。你会在本机安装 Python 依赖，构建一次 WebUI 静态资源，然后由 `python bot.py` 同时启动后端和管理面板。

如果你不想在宿主机安装 Python 与 Bun，请改看 [Docker 安装](docker-installation.md)。

## 1. 获取源码

```bash
git clone https://github.com/hsd221/riyabot.git
cd riyabot
```

## 2. 安装后端依赖

项目使用 [uv](https://github.com/astral-sh/uv) 管理 Python 依赖：

```bash
uv sync
```

## 3. 构建 WebUI 静态资源

源码安装时，后端会从 `webui/dist/` 托管前端静态文件。这个目录不提交到仓库，因此首次启动前需要在本机生成：

```bash
cd webui
bun install
bun run build
cd ..
```

## 4. 启动 RiyaBot

```bash
python bot.py
```

`bot.py` 采用 Runner/Worker 双进程模型：Runner 作为守护进程启动并监控 Worker，Worker 退出码为 `42` 时触发重启。首次启动时：

- 如果没有 `.env`，会依据 `template/template.env` 自动生成一份；
- 如果 EULA 或隐私协议尚未确认，主系统组件不会初始化，只启动 WebUI，交由首次配置向导处理；
- 配置文件（`config/bot_config.toml`、`config/model_config.toml`）会根据 `src/config/` 中的定义自动生成，无需手工复制模板。

`config/`、`data/`、`logs/` 是运行时目录，不应提交到仓库。

## 5. 完成首次配置

WebUI 后端随主程序一起启动，默认监听 `127.0.0.1:8001`（可通过环境变量 `WEBUI_HOST` / `WEBUI_PORT` 修改）。打开 http://127.0.0.1:8001，按配置向导完成：

1. 确认 EULA 和隐私协议；
2. 填写 bot 身份信息（平台、QQ 账号、昵称）；
3. 在模型管理中填写模型供应商、模型和 API Key，并完成任务分配。

初始模型配置**不预置**任何厂商、模型或密钥，必须在向导中填写。至少需要配置一个用于回复的语言模型；启用记忆、识图、语音等功能还需相应的 embedding / VLM / ASR 模型。

详细配置项见[配置指南](configuration.md)。

## 6. 连接聊天平台

RiyaBot 通过**适配器（Adapter）**连接 QQ 等消息平台。适配器与核心之间使用旧版消息 WebSocket 通信，默认在 `127.0.0.1:8000`（由 `.env` 的 `HOST` / `PORT` 控制）。跨主机连接时需要为核心与适配器配置同一个令牌，详见[部署指南](deployment.md)。

## 7. 参与 WebUI 开发

日常使用不需要单独运行前端开发服务器。需要修改 React 管理面板时，在 RiyaBot 运行后另开终端：

```bash
cd webui
bun install
bun run dev
```

修改完成后重新构建生产静态资源：

```bash
bun run build
```

## 下一步

- [Docker 安装](docker-installation.md) — 使用 Compose 运行核心、适配器和 NapCat。
- [配置说明](configuration.md) — 了解 WebUI 中各配置项与生成的 TOML 文件。
- [部署指南](deployment.md) — 配置跨主机连接、端口边界和运行时目录。
