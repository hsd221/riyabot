# 部署指南

本文说明源码安装和 Docker 安装共用的网络边界、适配器连接方式与运行时目录。选择安装方式前，先看[源码安装](installation.md)或[Docker 安装](docker-installation.md)。

## 选择部署方式

- [源码安装](installation.md) — 在宿主机安装 Python 与 Bun，适合开发和调试。
- [Docker 安装](docker-installation.md) — 使用 Compose 运行核心、适配器和 NapCat，适合长期运行。

## 组件构成

一个完整的 RiyaBot 部署通常包含三部分：

- **核心（core）**：RiyaBot 本体，负责聊天行为、记忆、插件与 WebUI；
- **适配器（adapters）**：把 QQ 等平台的消息协议转换成 RiyaBot 使用的旧版消息协议；
- **协议端（如 NapCat）**：真正登录 QQ 账号、收发底层消息的客户端。

核心与适配器之间通过**旧版消息 WebSocket**通信。它默认只监听回环地址，跨主机连接时需要显式配置监听地址和共享令牌。

## 跨主机和跨容器连接

核心与适配器不在同一台主机或同一网络命名空间时，先生成一个强随机令牌，再把同一个值配置给双方：

```bash
export MAIBOT_LEGACY_SERVER_TOKEN="$(openssl rand -hex 32)"
```

旧版适配器镜像如果不支持令牌变量，可以暂时开启匿名兼容模式：

```bash
export MAIBOT_LEGACY_SERVER_TOKEN=
export MAIBOT_ALLOW_UNAUTHENTICATED_LEGACY_SERVER=1
```

这个兼容开关只适用于受信的私有网络。不要把核心的旧版消息端口发布到公网；适配器升级后，应改回共享令牌并关闭兼容开关。

## 端口与环境变量

源码安装首次启动时会根据 `template/template.env` 自动生成 `.env`。Docker 安装通过 Compose 环境变量覆盖宿主机端口映射。常用配置如下：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `HOST` | `127.0.0.1` | 旧版消息服务器监听地址 |
| `PORT` | `8000` | 核心与适配器使用的旧版消息端口 |
| `WEBUI_HOST` | `127.0.0.1` | WebUI 服务监听地址 |
| `WEBUI_PORT` | `8001` | WebUI 服务端口 |
| `MAIBOT_LEGACY_SERVER_TOKEN` | 空 | 核心与适配器共享的连接令牌 |
| `MAIBOT_ALLOW_UNAUTHENTICATED_LEGACY_SERVER` | `0` | 是否允许旧版消息服务器远程匿名监听 |

上表中的 `HOST`、`WEBUI_HOST` 默认值适用于源码安装的回环监听。Docker 安装需要按[Docker 安装](docker-installation.md)中的首次准备步骤，把挂载到容器内的 `.env` 设置为 `HOST=0.0.0.0`、`WEBUI_HOST=0.0.0.0`，并写入核心与适配器共用的令牌。Docker 宿主机是否对外监听，则由下面的 `RIYABOT_WEBUI_BIND_ADDRESS` 等映射变量单独决定。

Docker Compose 另外提供以下宿主机映射变量：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `RIYABOT_WEBUI_BIND_ADDRESS` | `127.0.0.1` | Docker WebUI 端口的宿主机监听地址 |
| `RIYABOT_WEBUI_PORT` | `18001` | Docker WebUI 的宿主机端口 |
| `NAPCAT_BIND_ADDRESS` | `127.0.0.1` | NapCat 管理端口的宿主机监听地址 |
| `NAPCAT_PORT` | `6099` | NapCat 管理端口的宿主机端口 |

需要公网访问 WebUI 时，只开放 WebUI 端口并放在受控的 HTTPS 入口后面。不要同时发布 `8000`，也不要为了调试把旧版消息服务改成匿名公网监听。

## 运行时目录

源码安装使用项目根目录的 `config/`、`data/` 和 `logs/` 保存运行时状态。Docker 安装把对应内容持久化到宿主机的 `docker-config/` 和 `data/RiyaBot/`，具体映射见[Docker 安装](docker-installation.md)。

这些目录不是源码，不应提交到仓库。升级或迁移前，请先备份配置、数据库、插件和日志中需要保留的内容。

## 程序更新

WebUI 的“系统设置 > 关于”可以检查并切换更新频道：

- **正式版**：跟踪 `main` 分支可达的最新正式 SemVer 标签，不含预发布版本；
- **开发版**：跟踪远端 `dev` 分支的完整提交 SHA。

源码安装在当前提交可识别、受跟踪文件无修改、目标为快进提交且 `git`、`uv`、`bun` 均可用时，可由 Runner 执行一键更新并重启。目标落后、分支分叉或检查结果变化时，更新会被拒绝，不会强制重置或降级。

Docker 不会在运行中的容器内替换自身。更新 Docker 部署时，请按照[Docker 安装](docker-installation.md)中的流程拉取新源码、备份持久化目录并重新构建容器。

## 相关文档

- [配置说明](configuration.md) — 了解 WebUI 配置向导和生成的 TOML 文件。
- [架构概览](architecture.md) — 了解 Runner、Worker、核心服务与适配器的关系。
