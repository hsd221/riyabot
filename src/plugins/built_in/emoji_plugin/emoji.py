import json
from typing import Tuple

# 导入新插件系统
from src.plugin_system import BaseAction, ActionActivationType

# 导入依赖的系统组件
from src.common.logger import get_logger
from src.common.prompt_manager import prompt_manager

# 导入API模块 - 标准Python包方式
from src.plugin_system.apis import emoji_api, llm_api, message_api

# NoReplyAction已集成到heartFC_chat.py中，不再需要导入
from src.config.config import global_config


logger = get_logger("emoji")


class EmojiAction(BaseAction):
    """表情动作 - 发送表情包"""

    activation_type = ActionActivationType.RANDOM
    random_activation_probability = global_config.emoji.emoji_chance
    parallel_action = True

    # 动作基本信息
    action_name = "emoji"
    action_description = "发送表情包辅助表达情绪"

    # 动作参数定义
    action_parameters = {}

    # 动作使用场景
    action_require = [
        "发送表情包辅助表达情绪",
        "表达情绪时可以选择使用",
        "不要连续发送，如果你已经发过[表情包]，就不要选择此动作",
    ]

    # 关联类型
    associated_types = ["emoji"]

    async def execute(self) -> Tuple[bool, str]:
        # sourcery skip: assign-if-exp, introduce-default-else, swap-if-else-branches, use-named-expression
        """执行表情动作"""
        try:
            # 1. 获取发送表情的原因
            # reason = self.action_data.get("reason", "表达当前情绪")
            reason = self.action_reasoning

            # 2. 随机获取候选表情包，并为本轮选择分配临时 ID
            sampled_emojis = await emoji_api.get_random(30)
            if not sampled_emojis:
                logger.warning(f"{self.log_prefix} 无法获取随机表情包")
                return False, "无法获取随机表情包"

            candidates: dict[str, tuple[str, str]] = {}
            candidate_records: list[dict[str, str]] = []
            for index, (emoji_base64, description, emotion) in enumerate(sampled_emojis, start=1):
                candidate_id = f"emoji_{index:03d}"
                description = str(description).strip() if description else f"情感标签：{emotion or '未标注'}"
                candidates[candidate_id] = (emoji_base64, description)
                candidate_records.append({"id": candidate_id, "description": description})

            emoji_candidates = "\n".join(json.dumps(candidate, ensure_ascii=False) for candidate in candidate_records)

            # 3. 获取最近的5条消息内容用于判断
            recent_messages = message_api.get_recent_messages(chat_id=self.chat_id, limit=5)
            messages_text = ""
            if recent_messages:
                messages_text = message_api.build_readable_messages(
                    messages=recent_messages,
                    timestamp_mode="normal_no_YMD",
                    truncate=False,
                    show_actions=False,
                )

            prompt = prompt_manager.format_prompt(
                "media.emoji.selection",
                reason=reason,
                messages_text=messages_text,
                emoji_candidates=emoji_candidates,
            )

            if global_config.debug.show_prompt:
                logger.info(f"{self.log_prefix} 生成的LLM Prompt: {prompt}")
            else:
                logger.debug(f"{self.log_prefix} 生成的LLM Prompt: {prompt}")

            # 4. 调用LLM选择具体候选 ID
            models = llm_api.get_available_models()
            chat_model_config = models.get("utils")  # 使用字典访问方式
            if not chat_model_config:
                logger.error(f"{self.log_prefix} 未找到'utils'模型配置，无法调用LLM")
                return False, "未找到'utils'模型配置"

            success, selected_id, _, _ = await llm_api.generate_with_model(
                prompt,
                model_config=chat_model_config,
                request_type="emoji.select",
                temperature=0.1,
                max_tokens=20,
            )

            if not success:
                logger.error(f"{self.log_prefix} LLM调用失败: {selected_id}")
                return False, f"LLM调用失败: {selected_id}"

            selected_id = selected_id.strip().strip("`").strip().strip('"').strip("'").strip()
            selected_emoji = candidates.get(selected_id)
            if selected_emoji is None:
                logger.warning(f"{self.log_prefix} LLM返回的表情包候选 ID 无效: {selected_id!r}")
                return False, f"表情包候选 ID 无效: {selected_id}"

            emoji_base64, emoji_description = selected_emoji
            logger.info(
                f"{self.log_prefix} 发送表情包候选[{selected_id}]，原因: {reason}，描述: {emoji_description[:80]}"
            )

            # 5. 发送表情包
            success = await self.send_emoji(emoji_base64)

            if success:
                # 存储动作信息
                await self.store_action_info(
                    action_build_into_prompt=True,
                    action_prompt_display=f"你发送了表情包，原因：{reason}",
                    action_done=True,
                )
                return True, f"成功发送表情包:[表情包：{emoji_description}]"
            else:
                error_msg = "发送表情包失败"
                logger.error(f"{self.log_prefix} {error_msg}")

                await self.send_text("执行表情包动作失败")
                return False, error_msg

        except Exception as e:
            logger.error(f"{self.log_prefix} 表情动作执行失败: {e}", exc_info=True)
            return False, f"表情发送失败: {str(e)}"
