---
layout: home

hero:
  name: RiyaBot
  text: 璃夜Bot
  tagline: 一个面向 QQ 群聊的拟生命体聊天机器人，基于大语言模型、长期记忆、行为规划和插件系统构建。
  actions:
    - theme: brand
      text: 源码安装
      link: /guide/installation
    - theme: alt
      text: 插件开发
      link: /plugins/index
    - theme: alt
      text: GitHub
      link: https://github.com/hsd221/riyabot

features:
  - title: 群聊行为规划
    details: 根据聊天上下文决定回复、等待、使用动作或插件，而不是被动等待命令。
  - title: 长期记忆与人物关系
    details: 记录用户、群聊、表达方式和知识片段，用于后续交互，形成持续演化的记忆。
  - title: 拟人化表达
    details: 通过 Prompt、情绪、表情包和表达学习生成更自然的回复。
  - title: 插件系统
    details: 支持 Action、Command、Tool、Event 等扩展组件，提供稳定的开发 API。
  - title: Web 管理面板
    details: 提供配置、日志、插件、资源、人物关系和本地聊天管理。
  - title: 适配器部署
    details: 默认面向 QQ/NapCat 等 bot 协议适配场景，支持 Docker 一键部署。
---

## 关于 RiyaBot

RiyaBot 不是只等命令的工具型 bot，而更像一个长期停留在群聊里的虚拟角色：观察上下文、决定何时说话、学习群友表达、使用表情和插件，并在持续互动中形成自己的记忆与行为习惯。项目 fork 自 MaiBot/MaiCore，遵循 GPL-3.0。

## 快速导航

### 安装与使用

- [源码安装](/guide/installation) — 在本机安装依赖、构建 WebUI、启动后端并完成首次配置
- [Docker 安装](/guide/docker-installation) — 用 Compose 启动核心、适配器和 NapCat
- [配置说明](/guide/configuration) — `bot_config.toml` / `model_config.toml` 字段与首次配置向导
- [部署指南](/guide/deployment) — 跨主机令牌、端口安全与运行时目录
- [架构概览](/guide/architecture) — 进程模型、目录结构与各核心模块职责

### 插件开发

- [插件开发文档](/plugins/index) — 插件系统总览与 API 索引
- [快速开始](/plugins/quick-start) — 从零创建你的第一个插件
