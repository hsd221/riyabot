# RiyaBot 贡献指南

感谢您愿意为 RiyaBot 贡献时间和想法。本指南说明如何提交 Issue、发起 Pull Request 以及完成提交前的检查。

## 提交 Issue

提交 Issue 前，请先搜索已有 Issue，并尽量提供可复现、可核对的事实：

- RiyaBot 所在的分支和完整 commit SHA；
- 安装方式，例如源码、Docker Compose 或其他部署方式；
- 操作系统，以及 Python、uv、Bun、Docker 和适配器的版本；
- 预期行为、实际行为和最小复现步骤；
- 相关日志、请求时间和截图；
- 如果问题涉及模型供应商、平台风控、适配器或网络，请区分已观察到的外部状态和仍未验证的部分。

提交的日志中必须删除 Token、Cookie、平台账号、API Key、模型响应中的隐私内容和其他凭据。不要把"可能是某个外部服务导致"当作结论，除非日志或对照测试能够支持这一判断。

## 选择改动入口

- 文档错误、示例修正或文档站调整，直接发起 Pull Request 即可。
- 如果个人需求可以通过插件、Prompt 或本地配置解决，应优先使用这些扩展点。
- 如果改动会改变聊天行为、角色人格、插件 API、配置结构、数据库 schema、Docker 路径或 WebUI 主要交互，请先提交 Issue，说明问题和兼容性影响。

只要涉及配置、数据库、认证、插件或 Docker 路径，就必须同时说明旧版本如何继续运行、是否需要迁移，以及失败时如何恢复。

## Pull Request 要求

**工作流程**：从 `dev` 创建分支 → 提交改动 → 通过 PR 合入 `dev` → 在 `dev` 验证后合并到 `main`。普通改动不直接提交或合并到 `main`，也不要直接提交 `dev`（除非得到维护者授权）。提交信息使用 Conventional Commits 前缀（`feat:`、`fix:`、`docs:`、`refactor:`、`chore:` 等）。

一个 PR 只解决一个主要问题。无关的重命名、格式化、依赖升级或重构，不应混入功能改动。

PR 描述至少应包含：

- **问题**：说明改动解决了什么可观察的问题；
- **方案**：说明改动涉及哪些模块，以及为什么放在这些边界；
- **兼容性**：说明是否影响配置、数据目录、插件 API、数据库、认证或 Docker 部署；
- **验证**：列出实际运行过的命令及结果；
- **风险与回滚**：如果需要迁移、备份或特殊发布顺序，写明操作方法。

如果文档、配置或 API 行为发生变化，同一个 PR 必须更新对应文档和交叉链接。不要将生成文件当作源码修改。

## 提交前检查

根据改动范围运行对应检查。完整的后端改动至少运行：

```bash
ruff check .
ruff format --check .
uv run python -m unittest discover -s tests -p 'test_*.py'
```

涉及 WebUI 的改动运行：

```bash
(cd webui && bun install --frozen-lockfile && bun run lint && bun run build)
```

涉及文档站的改动运行：

```bash
(cd docs-src && bun install --frozen-lockfile && bun run docs:build)
```

改动范围较窄时，可以只运行受影响的检查。但必须在 PR 中说明未运行哪些检查及原因。不要把“代码未执行”写成“验证通过”。

## 不要提交的内容

提交前请检查工作树，以下内容属于本地或生成状态，不应提交：

- `.env`、Token、Cookie、API Key 和其他凭据；
- `config/`、`data/`、`logs/`、`tests/artifacts/` 以及私有数据库；
- `webui/dist/`（`main` 分支由 CI 自动构建提交，其他分支不要手动提交）、`webui/node_modules/`、`docs-src/.vitepress/dist/`、`docs-src/node_modules/` 和缓存；
- 模型原始响应、上传文件、适配器流量，以及包含个人信息的聊天记录。

插件输入、模型输出、上传内容、远程响应和适配器数据都必须按不可信数据处理。新增代码需要限制路径、网络请求和日志内容；不能把这些数据直接当成可信指令执行。

## 代码和文档风格

- Python 使用四个空格、双引号和 120 字符行宽；Ruff 负责检查 `E`、`F`、`B` 规则；
- WebUI 保持 React 19、TypeScript、Vite 和现有格式化配置；
- 插件应从 `src.plugin_system` 或 `src.plugin_system.apis` 导入公共接口，不要直接依赖运行时 `core/` 内部实现；
- 新增工具、缓存、日志、数据库连接、配置写入或认证检查前，请先查找并复用现有公共边界；
- 文档使用项目已有的标题、链接和代码块风格；文件路径以仓库根目录为基准表达。

## 法律和许可

提交代码或文档即表示您确认以下事项：

- 您有权贡献这些内容；
- 这些内容可以按本项目 GPL-3.0 许可发布；
- 您没有提交秘密、私有数据库、运行日志、Token、API Key 或其他敏感信息。

RiyaBot fork 自 MaiBot/MaiCore，并继续遵循 GPL-3.0 许可。涉及上游代码的改动，应保留原项目作者与贡献者的署名和许可要求。
