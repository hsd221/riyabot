<div align="center">
  <h1>RiyaBot 文档</h1>
  <p>一个面向 QQ 群聊的拟生命体聊天机器人，基于大语言模型、长期记忆、行为规划和插件系统构建。</p>
</div>

RiyaBot 不是只等命令的工具型 bot，而更像一个长期停留在群聊里的虚拟角色：观察上下文、决定何时说话、学习群友表达、使用表情和插件，并在持续互动中形成自己的记忆与行为习惯。项目 fork 自 MaiBot/MaiCore，遵循 GPL-3.0。

## 快速导航

### 部署与使用

- [安装与启动](guide/installation.md) — 从源码安装、准备配置、启动后端与 WebUI
- [配置说明](guide/configuration.md) — `bot_config.toml` / `model_config.toml` 字段与首次配置向导
- [部署指南](guide/deployment.md) — Docker Compose、跨主机令牌、端口与运行时目录
- [架构概览](guide/architecture.md) — 进程模型、目录结构与各核心模块职责

### 插件开发

- [插件开发文档](plugins/index.md) — 插件系统总览与 API 索引
- [快速开始](plugins/quick-start.md) — 从零创建你的第一个插件

## 核心能力

- **群聊行为规划**：根据聊天上下文决定回复、等待、使用动作或插件。
- **长期记忆与人物关系**：记录用户、群聊、表达方式和知识片段，用于后续交互。
- **拟人化表达**：通过 Prompt、情绪、表情包和表达学习生成更自然的回复。
- **插件系统**：支持 Action、Command、Tool、Event 等扩展组件。
- **Web 管理面板**：提供配置、日志、插件、资源、人物关系和本地聊天管理。
- **适配器部署**：默认面向 QQ/NapCat 等 bot 协议适配场景。

## 来源与许可

RiyaBot fork 自 MaiBot/MaiCore，并继续遵循原项目的 GPL-3.0 开源许可。使用前请阅读仓库中的 EULA 与隐私协议。
