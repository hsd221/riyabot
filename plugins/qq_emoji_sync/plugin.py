"""QQ 收藏表情同步命令插件。"""

import asyncio

from typing import List, Tuple, Type

from src.common.logger import get_logger
from src.plugin_system import BaseCommand, BasePlugin, CommandInfo, ConfigField, register_plugin

from .sync_service import MAX_PENDING_FILES, MAX_SYNC_COUNT, QQEmojiSyncError, QQEmojiSyncService

logger = get_logger("qq_emoji_sync")

_sync_lock = asyncio.Lock()


def _config_int(value: object, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if minimum <= parsed <= maximum else default


class QQEmojiSyncCommand(BaseCommand):
    command_name = "qq_emoji_sync"
    command_description = "将 NapCat 当前账号的收藏表情同步到待注册目录"
    command_pattern = r"^(?:/qqemoji|/同步QQ表情)(?:\s+(?P<count>\d{1,4}))?\s*$"

    async def execute(self) -> Tuple[bool, str, int]:
        user_info = getattr(getattr(self.message, "message_info", None), "user_info", None)
        user_id = str(getattr(user_info, "user_id", ""))
        configured_permissions = self.get_config("plugin.permission", [])
        permissions = (
            {str(item) for item in configured_permissions} if isinstance(configured_permissions, list) else set()
        )

        if not permissions:
            await self.send_text("QQ 表情同步插件尚未配置可用用户，请先设置 plugin.permission", storage_message=False)
            return False, "未配置权限", 2
        if not user_id or user_id not in permissions:
            await self.send_text("你没有权限使用 QQ 表情同步命令", storage_message=False)
            return False, "没有权限", 2

        max_count = _config_int(self.get_config("sync.max_count", 500), 500, 1, MAX_SYNC_COUNT)
        default_count = _config_int(
            self.get_config("sync.default_count", 10),
            min(10, max_count),
            1,
            max_count,
        )
        raw_count = self.matched_groups.get("count")
        try:
            count = default_count if not raw_count else int(raw_count)
        except (TypeError, ValueError):
            await self.send_text("同步数量必须是整数", storage_message=False)
            return False, "数量无效", 2
        if not 1 <= count <= max_count:
            await self.send_text(f"单次同步数量必须在 1 到 {max_count} 之间", storage_message=False)
            return False, "数量超限", 2

        if _sync_lock.locked():
            await self.send_text("已有 QQ 表情同步任务正在执行，请稍后再试", storage_message=False)
            return False, "同步忙", 2

        max_pending = _config_int(
            self.get_config("sync.max_pending", 1000),
            1000,
            1,
            MAX_PENDING_FILES,
        )
        await _sync_lock.acquire()
        try:
            await self.send_text(f"开始读取 QQ 收藏表情，最多处理 {count} 个……", storage_message=False)
            result = await QQEmojiSyncService(max_pending=max_pending).sync(count)
            await self.send_text(result.to_message(), storage_message=False)
            logger.info(
                "QQ 收藏表情同步完成",
                event_code="qq_emoji_sync.completed",
                requested=result.requested,
                fetched=result.fetched,
                queued=result.queued,
                duplicates=result.duplicates,
                rejected=result.rejected,
                failed=result.failed,
                capacity_reached=result.capacity_reached,
            )
            return True, "同步完成", 2
        except QQEmojiSyncError as exc:
            await self.send_text(str(exc), storage_message=False)
            return False, "同步失败", 2
        except Exception:
            logger.exception("QQ 收藏表情同步异常", event_code="qq_emoji_sync.command_exception")
            await self.send_text("QQ 收藏表情同步失败，请查看日志", storage_message=False)
            return False, "同步失败", 2
        finally:
            _sync_lock.release()


@register_plugin
class QQEmojiSyncPlugin(BasePlugin):
    plugin_name = "qq_emoji_sync"
    enable_plugin = True
    dependencies = ["onebot_adapter"]
    python_dependencies = []
    config_file_name = "plugin_config.toml"
    config_schema = {
        "plugin": {
            "enabled": ConfigField(bool, default=True, description="是否启用 QQ 收藏表情同步插件"),
            "config_version": ConfigField(str, default="1.1.0", description="配置文件版本"),
            "permission": ConfigField(
                list,
                default=[],
                description="允许执行同步命令的 QQ 号列表（字符串）",
                item_type="string",
                max_items=20,
            ),
        },
        "sync": {
            "default_count": ConfigField(
                int,
                default=10,
                description="命令未指定数量时的默认同步数量",
                min=1,
                max=MAX_SYNC_COUNT,
            ),
            "max_count": ConfigField(
                int,
                default=500,
                description="单次命令允许同步的最大数量",
                min=1,
                max=MAX_SYNC_COUNT,
            ),
            "max_pending": ConfigField(
                int,
                default=1000,
                description="待注册目录允许保留的最大条目数（包含其他文件）",
                min=1,
                max=MAX_PENDING_FILES,
            ),
        },
    }

    def get_plugin_components(self) -> List[Tuple[CommandInfo, Type[BaseCommand]]]:
        if not self.get_config("plugin.enabled", True):
            return []
        return [(QQEmojiSyncCommand.get_command_info(), QQEmojiSyncCommand)]
