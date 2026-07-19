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
    action_parameters = {
        "emotion": "用1到5个简短词概括希望表情包表达的情感或语气，例如“轻松调侃”“温柔安慰”",
        "scene": "用一句话概括当前准备发表情的具体聊天场景，例如“对方自嘲失败，准备轻松接梗”",
    }

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
            reason = str(self.action_reasoning or "表达当前情绪")
            current_scene = " ".join(str(self.action_data.get("scene") or "").split()).strip()[:1000]
            if not current_scene:
                current_scene = " ".join(reason.split()).strip()[:1000]

            candidate_count = max(1, min(int(getattr(global_config.emoji, "selection_candidate_count", 8)), 30))
            scene_weight = max(0.0, min(float(getattr(global_config.emoji, "usage_scene_weight", 0.6)), 1.0))
            usage_scene_enabled = bool(getattr(global_config.emoji, "usage_scene_enabled", True))

            # 2. 对情感与真人场景分别做向量召回，再按配置加权；不可用时保持随机回退。
            emotion_query = " ".join(str(self.action_data.get("emotion") or "").split()).strip()[:64]
            sampled_emojis = None
            if emotion_query:
                try:
                    sampled_emojis = await emoji_api.get_ranked_candidates(
                        emotion_query,
                        current_scene if usage_scene_enabled else "",
                        count=candidate_count,
                        scene_weight=scene_weight if usage_scene_enabled else 0.0,
                    )
                except Exception as vector_error:
                    logger.warning(f"{self.log_prefix} 表情向量检索异常，回退随机候选: {vector_error}")

                if sampled_emojis == []:
                    logger.info(f"{self.log_prefix} 没有表情包达到情感或场景向量相似度阈值")
                    return False, "没有表情包达到情感或场景相似度阈值"

            if sampled_emojis is None:
                sampled_emojis = await emoji_api.get_random_candidates(candidate_count)
            if not sampled_emojis:
                logger.warning(f"{self.log_prefix} 无法获取随机表情包")
                return False, "无法获取随机表情包"

            candidates: dict[str, emoji_api.EmojiSelectionCandidate] = {}
            candidate_records: list[dict[str, object]] = []
            for index, candidate in enumerate(sampled_emojis, start=1):
                candidate_id = f"emoji_{index:03d}"
                description = (
                    str(candidate.description).strip()
                    if candidate.description
                    else f"情感标签：{candidate.matched_emotion or '未标注'}"
                )
                candidates[candidate_id] = candidate
                candidate_record: dict[str, object] = {"id": candidate_id, "description": description}
                if candidate.usage_scenes:
                    candidate_record["human_usage_scenes"] = list(candidate.usage_scenes)
                candidate_records.append(candidate_record)

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
                current_scene=current_scene,
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

            emoji_description = selected_emoji.description
            logger.info(
                f"{self.log_prefix} 发送表情包候选[{selected_id}]，原因: {reason}，描述: {emoji_description[:80]}"
            )

            # 5. 发送表情包
            success = await self.send_emoji(selected_emoji.emoji_base64)

            if success:
                emoji_api.record_usage(selected_emoji.emoji_hash)
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
