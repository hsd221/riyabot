from typing import Tuple, List, Dict, Any
from src.common.logger import get_logger
from src.llm_models.utils_model import LLMRequest
from src.config.config import global_config
from .chat_observer import ChatObserver
from .reply_checker import ReplyChecker
from .observation_info import ObservationInfo
from .conversation_info import ConversationInfo
from .pfc_KnowledgeFetcher import format_knowledge_evidence, format_pfc_chat_history
from src.common.prompt_manager import prompt_manager

logger = get_logger("reply_generator")


class ReplyGenerator:
    """回复生成器"""

    def __init__(self, stream_id: str, private_name: str):
        self.llm = LLMRequest(
            model=global_config.llm_PFC_chat,
            temperature=global_config.llm_PFC_chat["temp"],
            max_tokens=300,
            request_type="reply_generation",
        )
        self.personality_info = self._get_personality_prompt()
        self.name = global_config.BOT_NICKNAME
        self.private_name = private_name
        self.chat_observer = ChatObserver.get_instance(stream_id, private_name)
        self.reply_checker = ReplyChecker(stream_id, private_name)

    def _get_personality_prompt(self) -> str:
        """获取个性提示信息"""
        prompt_personality = global_config.personality.personality

        bot_name = global_config.BOT_NICKNAME
        return f"你的名字是{bot_name},你{prompt_personality};"

    # 修改 generate 方法签名，增加 action_type 参数
    async def generate(
        self, observation_info: ObservationInfo, conversation_info: ConversationInfo, action_type: str
    ) -> str:
        """生成回复

        Args:
            observation_info: 观察信息
            conversation_info: 对话信息
            action_type: 当前执行的动作类型 ('direct_reply' 或 'send_new_message')

        Returns:
            str: 生成的回复
        """
        # 构建提示词
        logger.debug(
            f"[私聊][{self.private_name}]开始生成回复 (动作类型: {action_type})：当前目标: {conversation_info.goal_list}"
        )

        # --- 构建通用 Prompt 参数 ---
        # (这部分逻辑基本不变)

        # 构建对话目标 (goals_str)
        goals_str = ""
        if conversation_info.goal_list:
            for goal_reason in conversation_info.goal_list:
                if isinstance(goal_reason, dict):
                    goal = goal_reason.get("goal", "目标内容缺失")
                    reasoning = goal_reason.get("reasoning", "没有明确原因")
                else:
                    goal = str(goal_reason)
                    reasoning = "没有明确原因"

                goal = str(goal) if goal is not None else "目标内容缺失"
                reasoning = str(reasoning) if reasoning is not None else "没有明确原因"
                goals_str += f"- 目标：{goal}\n  原因：{reasoning}\n"
        else:
            goals_str = "- 目前没有明确对话目标\n"  # 简化无目标情况

        knowledge_info_str = format_knowledge_evidence(getattr(conversation_info, "knowledge_list", []))

        # 获取聊天历史记录 (chat_history_text)
        chat_history_text = observation_info.chat_history_str
        if observation_info.new_messages_count > 0 and observation_info.unprocessed_messages:
            new_messages_list = observation_info.unprocessed_messages
            new_messages_str = format_pfc_chat_history(new_messages_list)
            chat_history_text += f"\n--- 以下是 {observation_info.new_messages_count} 条新消息 ---\n{new_messages_str}"
        elif not chat_history_text:
            chat_history_text = "还没有聊天记录。"

        # 构建 Persona 文本 (persona_text)
        persona_text = f"你的名字是{self.name}，{self.personality_info}。"

        # --- 选择并格式化 Prompt ---
        if action_type == "send_new_message":
            prompt = prompt_manager.format_prompt(
                "chat.private.pfc.reply_generation.send_new_message",
                persona_text=persona_text,
                goals_str=goals_str,
                chat_history_text=chat_history_text,
                knowledge_info_str=knowledge_info_str,
            )
            logger.info(f"[私聊][{self.private_name}]使用 PROMPT_SEND_NEW_MESSAGE (追问生成)")
        elif action_type == "say_goodbye":  # 处理告别动作
            prompt = prompt_manager.format_prompt(
                "chat.private.pfc.reply_generation.farewell",
                persona_text=persona_text,
                goals_str=goals_str,
                chat_history_text=chat_history_text,
                knowledge_info_str=knowledge_info_str,
            )
            logger.info(f"[私聊][{self.private_name}]使用 PROMPT_FAREWELL (告别语生成)")
        else:  # 默认使用 direct_reply 的 prompt (包括 'direct_reply' 或其他未明确处理的类型)
            prompt = prompt_manager.format_prompt(
                "chat.private.pfc.reply_generation.direct_reply",
                persona_text=persona_text,
                goals_str=goals_str,
                chat_history_text=chat_history_text,
                knowledge_info_str=knowledge_info_str,
            )
            logger.info(f"[私聊][{self.private_name}]使用 PROMPT_DIRECT_REPLY (首次/非连续回复生成)")

        # --- 调用 LLM 生成 ---
        logger.debug(f"[私聊][{self.private_name}]发送到LLM的生成提示词:\n------\n{prompt}\n------")
        try:
            content, _ = await self.llm.generate_response_async(prompt)
            logger.debug(f"[私聊][{self.private_name}]生成的回复: {content}")
            # 移除旧的检查新消息逻辑，这应该由 conversation 控制流处理
            return content

        except Exception as e:
            logger.error(f"[私聊][{self.private_name}]生成回复时出错: {e}")
            return "抱歉，我现在有点混乱，让我重新思考一下..."

    # check_reply 方法保持不变
    async def check_reply(
        self, reply: str, goal: str, chat_history: List[Dict[str, Any]], chat_history_str: str, retry_count: int = 0
    ) -> Tuple[bool, str, bool]:
        """检查回复是否合适
        (此方法逻辑保持不变)
        """
        return await self.reply_checker.check(reply, goal, chat_history, chat_history_str, retry_count)
