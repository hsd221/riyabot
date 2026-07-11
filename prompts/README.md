# 提示词目录

提示词按业务领域存放，文件路径就是正式 ID。不要在 `prompts/` 根目录新增 `.prompt` 文件。

例如：

- `prompts/chat/group/planner.prompt` 对应 `chat.group.planner`
- `prompts/media/emoji/vision_description.prompt` 的 `static` 分段对应 `media.emoji.vision_description.static`

## 目录职责

| 目录 | 用途 |
| --- | --- |
| `chat/` | 群聊、私聊、PFC、回复与表达器 |
| `learning/` | 行为、表达方式和黑话学习 |
| `media/` | 音频转写、表情包识别与选择 |
| `memory/` | 记忆抽取、检索、判断与知识查询 |
| `shared/` | 多条业务链共用的审核和工具提示词 |

## 维护规则

1. 业务代码统一通过 `src.common.prompt_manager.prompt_manager` 获取或格式化提示词。
2. 同一任务的固定变体放在一个文件的 `###SECTION: name` 分段中，不复制整份文件。
3. 新文件使用简短的任务名，领域信息由目录表达，避免 `*_prompt`、`default_*_prompt` 之类重复前后缀。
4. 删除模板前先确认没有运行时引用，并同步更新 `tests/test_prompt_template_contracts.py`。
5. 旧 ID 的兼容只维护在 `LEGACY_PROMPT_ALIASES`，不要为兼容复制旧路径文件。
