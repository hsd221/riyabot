# RiyaBot 贡献指南

感谢你愿意改进 RiyaBot。这个项目仍在从上游 MaiBot/MaiCore fork 迁移到独立维护状态，因此贡献时请优先关注可验证、可维护、边界清晰的改动。

## 提问和反馈

提交 Issue 前请先搜索现有 Issue，并尽量提供：

- 版本、分支或 commit hash
- 运行方式：本地、Docker Compose 或自定义部署
- Python 版本、操作系统和关键依赖环境
- 复现步骤
- 关键日志或截图，注意删除 Token、Cookie、QQ 号、API Key 等敏感信息

如果问题可能由模型额度、平台风控、适配器配置或第三方服务导致，请先在本地排查这些外部因素。

## Pull Request

PR 请保持范围明确。一个 PR 最好只解决一个问题，避免把重命名、格式化、功能改动和重构混在一起。

提交前请说明：

- 修改内容和原因
- 是否影响配置、数据目录、插件 API、数据库或 Docker 部署
- 已经运行过的验证命令
- WebUI 改动的截图或录屏

推荐验证命令：

```bash
ruff check .
ruff format --check .
uv run python tests/run_e2e.py --quick
cd webui && bun run build
```

如果改动只涉及文档，可以说明未运行代码测试。

## 功能建议

新增功能请先开 Issue 讨论，尤其是以下类型：

- 改变聊天行为或角色人格
- 新增配置项或改动配置结构
- 改动插件 API
- 数据库 schema 迁移
- Docker、路径或运行时目录变更
- WebUI 大幅交互改版

如果只是个人使用场景，优先考虑通过插件、Prompt 或本地配置解决。

## 代码风格

- Python 使用 Ruff，双引号，行宽 120。
- WebUI 使用 React 19、TypeScript、Vite 和 Tailwind CSS。
- 保持现有模块边界，避免无关重构。
- 后端注释和文档可以使用中文，风格尽量贴近附近代码。

## 法律和许可

提交代码或文档即表示你确认：

- 你有权贡献这些内容。
- 这些内容可以按本项目 GPL-3.0 许可发布。
- 你没有提交秘密、私有数据库、运行日志、Token、API Key 或其他敏感信息。

RiyaBot fork 自 MaiBot/MaiCore，并继续遵循 GPL-3.0 许可。涉及上游代码的改动应尊重原项目作者与贡献者的署名和许可要求。
