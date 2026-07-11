import time
from typing import Tuple, Optional  # 增加了 Optional
from src.common.logger import get_logger
from src.llm_models.utils_model import LLMRequest
from src.config.config import global_config
import random
from .chat_observer import ChatObserver
from .pfc_utils import get_items_from_json
from .observation_info import ObservationInfo
from .conversation_info import ConversationInfo
from .pfc_KnowledgeFetcher import format_knowledge_evidence, format_pfc_chat_history
from src.common.prompt_manager import prompt_manager


logger = get_logger("pfc_action_planner")


# ActionPlanner 类定义，顶格
class ActionPlanner:
    """行动规划器"""

    def __init__(self, stream_id: str, private_name: str):
        self.llm = LLMRequest(
            model=global_config.llm_PFC_action_planner,
            temperature=global_config.llm_PFC_action_planner["temp"],
            max_tokens=1500,
            request_type="action_planning",
        )
        self.personality_info = self._get_personality_prompt()
        self.name = global_config.BOT_NICKNAME
        self.private_name = private_name
        self.chat_observer = ChatObserver.get_instance(stream_id, private_name)
        # self.action_planner_info = ActionPlannerInfo() # 移除未使用的变量

    def _get_personality_prompt(self) -> str:
        """获取个性提示信息"""
        prompt_personality = global_config.personality.personality

        # 检查是否需要随机替换为状态
        if (
            global_config.personality.states
            and global_config.personality.state_probability > 0
            and random.random() < global_config.personality.state_probability
        ):
            prompt_personality = random.choice(global_config.personality.states)

        bot_name = global_config.BOT_NICKNAME
        return f"你的名字是{bot_name},你{prompt_personality};"

    # 修改 plan 方法签名，增加 last_successful_reply_action 参数
    async def plan(
        self,
        observation_info: ObservationInfo,
        conversation_info: ConversationInfo,
        last_successful_reply_action: Optional[str],
    ) -> Tuple[str, str]:
        """规划下一步行动

        Args:
            observation_info: 决策信息
            conversation_info: 对话信息
            last_successful_reply_action: 上一次成功的回复动作类型 ('direct_reply' 或 'send_new_message' 或 None)

        Returns:
            Tuple[str, str]: (行动类型, 行动原因)
        """
        # --- 获取 Bot 上次发言时间信息 ---
        # (这部分逻辑不变)
        time_since_last_bot_message_info = ""
        try:
            bot_id = str(global_config.BOT_QQ)
            if hasattr(observation_info, "chat_history") and observation_info.chat_history:
                for i in range(len(observation_info.chat_history) - 1, -1, -1):
                    msg = observation_info.chat_history[i]
                    if not isinstance(msg, dict):
                        continue
                    sender_info = msg.get("user_info", {})
                    sender_id = str(sender_info.get("user_id")) if isinstance(sender_info, dict) else None
                    msg_time = msg.get("time")
                    if sender_id == bot_id and msg_time:
                        time_diff = time.time() - msg_time
                        if time_diff < 60.0:
                            time_since_last_bot_message_info = (
                                f"提示：你上一条成功发送的消息是在 {time_diff:.1f} 秒前。\n"
                            )
                        break
            else:
                logger.debug(
                    f"[私聊][{self.private_name}]Observation info chat history is empty or not available for bot time check."
                )
        except AttributeError:
            logger.warning(
                f"[私聊][{self.private_name}]ObservationInfo object might not have chat_history attribute yet for bot time check."
            )
        except Exception as e:
            logger.warning(f"[私聊][{self.private_name}]获取 Bot 上次发言时间时出错: {e}")

        # --- 获取超时提示信息 ---
        # (这部分逻辑不变)
        timeout_context = ""
        try:
            if hasattr(conversation_info, "goal_list") and conversation_info.goal_list:
                last_goal_dict = conversation_info.goal_list[-1]
                if isinstance(last_goal_dict, dict) and "goal" in last_goal_dict:
                    last_goal_text = last_goal_dict["goal"]
                    if isinstance(last_goal_text, str) and "分钟，思考接下来要做什么" in last_goal_text:
                        try:
                            timeout_minutes_text = last_goal_text.split("，")[0].replace("你等待了", "")
                            timeout_context = f"重要提示：对方已经长时间（{timeout_minutes_text}）没有回复你的消息了（这可能代表对方繁忙/不想回复/没注意到你的消息等情况，或在对方看来本次聊天已告一段落），请基于此情况规划下一步。\n"
                        except Exception:
                            timeout_context = "重要提示：对方已经长时间没有回复你的消息了（这可能代表对方繁忙/不想回复/没注意到你的消息等情况，或在对方看来本次聊天已告一段落），请基于此情况规划下一步。\n"
            else:
                logger.debug(
                    f"[私聊][{self.private_name}]Conversation info goal_list is empty or not available for timeout check."
                )
        except AttributeError:
            logger.warning(
                f"[私聊][{self.private_name}]ConversationInfo object might not have goal_list attribute yet for timeout check."
            )
        except Exception as e:
            logger.warning(f"[私聊][{self.private_name}]检查超时目标时出错: {e}")

        # --- 构建通用 Prompt 参数 ---
        logger.debug(
            f"[私聊][{self.private_name}]开始规划行动：当前目标: {getattr(conversation_info, 'goal_list', '不可用')}"
        )

        # 构建对话目标 (goals_str)
        goals_str = ""
        try:
            if hasattr(conversation_info, "goal_list") and conversation_info.goal_list:
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

                if not goals_str:
                    goals_str = "- 目前没有明确对话目标，请考虑设定一个。\n"
            else:
                goals_str = "- 目前没有明确对话目标，请考虑设定一个。\n"
        except AttributeError:
            logger.warning(
                f"[私聊][{self.private_name}]ConversationInfo object might not have goal_list attribute yet."
            )
            goals_str = "- 获取对话目标时出错。\n"
        except Exception as e:
            logger.error(f"[私聊][{self.private_name}]构建对话目标字符串时出错: {e}")
            goals_str = "- 构建对话目标时出错。\n"

        knowledge_info_str = format_knowledge_evidence(getattr(conversation_info, "knowledge_list", []))

        # 获取聊天历史记录 (chat_history_text)
        try:
            if hasattr(observation_info, "chat_history") and observation_info.chat_history:
                chat_history_text = observation_info.chat_history_str
                if not chat_history_text:
                    chat_history_text = "还没有聊天记录。\n"
            else:
                chat_history_text = "还没有聊天记录。\n"

            if hasattr(observation_info, "new_messages_count") and observation_info.new_messages_count > 0:
                if hasattr(observation_info, "unprocessed_messages") and observation_info.unprocessed_messages:
                    new_messages_list = observation_info.unprocessed_messages
                    new_messages_str = format_pfc_chat_history(new_messages_list)
                    chat_history_text += (
                        f"\n--- 以下是 {observation_info.new_messages_count} 条新消息 ---\n{new_messages_str}"
                    )
                else:
                    logger.warning(
                        f"[私聊][{self.private_name}]ObservationInfo has new_messages_count > 0 but unprocessed_messages is empty or missing."
                    )
        except AttributeError:
            logger.warning(
                f"[私聊][{self.private_name}]ObservationInfo object might be missing expected attributes for chat history."
            )
            chat_history_text = "获取聊天记录时出错。\n"
        except Exception as e:
            logger.error(f"[私聊][{self.private_name}]处理聊天记录时发生未知错误: {e}")
            chat_history_text = "处理聊天记录时出错。\n"

        # 构建 Persona 文本 (persona_text)
        persona_text = f"你的名字是{self.name}，{self.personality_info}。"

        # 构建行动历史和上一次行动结果 (action_history_summary, last_action_context)
        # (这部分逻辑不变)
        action_history_summary = "你最近执行的行动历史：\n"
        last_action_context = "关于你【上一次尝试】的行动：\n"
        action_history_list = []
        try:
            if hasattr(conversation_info, "done_action") and conversation_info.done_action:
                action_history_list = conversation_info.done_action[-5:]
            else:
                logger.debug(f"[私聊][{self.private_name}]Conversation info done_action is empty or not available.")
        except AttributeError:
            logger.warning(
                f"[私聊][{self.private_name}]ConversationInfo object might not have done_action attribute yet."
            )
        except Exception as e:
            logger.error(f"[私聊][{self.private_name}]访问行动历史时出错: {e}")

        if not action_history_list:
            action_history_summary += "- 还没有执行过行动。\n"
            last_action_context += "- 这是你规划的第一个行动。\n"
        else:
            for i, action_data in enumerate(action_history_list):
                action_type = "未知"
                plan_reason = "未知"
                status = "未知"
                final_reason = ""
                action_time = ""

                if isinstance(action_data, dict):
                    action_type = action_data.get("action", "未知")
                    plan_reason = action_data.get("plan_reason", "未知规划原因")
                    status = action_data.get("status", "未知")
                    final_reason = action_data.get("final_reason", "")
                    action_time = action_data.get("time", "")
                elif isinstance(action_data, tuple):
                    # 假设旧格式兼容
                    if len(action_data) > 0:
                        action_type = action_data[0]
                    if len(action_data) > 1:
                        plan_reason = action_data[1]  # 可能是规划原因或最终原因
                    if len(action_data) > 2:
                        status = action_data[2]
                    if status == "recall" and len(action_data) > 3:
                        final_reason = action_data[3]
                    elif status == "done" and action_type in ["direct_reply", "send_new_message"]:
                        plan_reason = "成功发送"  # 简化显示

                reason_text = f", 失败/取消原因: {final_reason}" if final_reason else ""
                summary_line = f"- 时间:{action_time}, 尝试行动:'{action_type}', 状态:{status}{reason_text}"
                action_history_summary += summary_line + "\n"

                if i == len(action_history_list) - 1:
                    last_action_context += f"- 上次【规划】的行动是: '{action_type}'\n"
                    last_action_context += f"- 当时规划的【原因】是: {plan_reason}\n"
                    if status == "done":
                        last_action_context += "- 该行动已【成功执行】。\n"
                        # 记录这次成功的行动类型，供下次决策
                        # self.last_successful_action_type = action_type # 不在这里记录，由 conversation 控制
                    elif status == "recall":
                        last_action_context += "- 但该行动最终【未能执行/被取消】。\n"
                        if final_reason:
                            last_action_context += f"- 【重要】失败/取消的具体原因是: “{final_reason}”\n"
                        else:
                            last_action_context += "- 【重要】失败/取消原因未明确记录。\n"
                        # self.last_successful_action_type = None # 行动失败，清除记录
                    else:
                        last_action_context += f"- 该行动当前状态: {status}\n"
                        # self.last_successful_action_type = None # 非完成状态，清除记录

        # --- 选择并格式化 Prompt ---
        if last_successful_reply_action in ["direct_reply", "send_new_message"]:
            prompt = prompt_manager.format_prompt(
                "chat.private.pfc.action_decision.follow_up",
                persona_text=persona_text,
                goals_str=goals_str if goals_str.strip() else "- 目前没有明确对话目标，请考虑设定一个。",
                action_history_summary=action_history_summary,
                last_action_context=last_action_context,
                time_since_last_bot_message_info=time_since_last_bot_message_info,
                timeout_context=timeout_context,
                chat_history_text=chat_history_text if chat_history_text.strip() else "还没有聊天记录。",
                knowledge_info_str=knowledge_info_str,
            )
            logger.debug(f"[私聊][{self.private_name}]使用 PROMPT_FOLLOW_UP (追问决策)")
        else:
            prompt = prompt_manager.format_prompt(
                "chat.private.pfc.action_decision.initial_reply",
                persona_text=persona_text,
                goals_str=goals_str if goals_str.strip() else "- 目前没有明确对话目标，请考虑设定一个。",
                action_history_summary=action_history_summary,
                last_action_context=last_action_context,
                time_since_last_bot_message_info=time_since_last_bot_message_info,
                timeout_context=timeout_context,
                chat_history_text=chat_history_text if chat_history_text.strip() else "还没有聊天记录。",
                knowledge_info_str=knowledge_info_str,
            )
            logger.debug(f"[私聊][{self.private_name}]使用 PROMPT_INITIAL_REPLY (首次/非连续回复决策)")

        logger.debug(f"[私聊][{self.private_name}]发送到LLM的最终提示词:\n------\n{prompt}\n------")
        try:
            content, _ = await self.llm.generate_response_async(prompt)
            logger.debug(f"[私聊][{self.private_name}]LLM (行动规划) 原始返回内容: {content}")

            # --- 初始行动规划解析 ---
            success, initial_result = get_items_from_json(
                content,
                self.private_name,
                "action",
                "reason",
                default_values={"action": "wait", "reason": "LLM返回格式错误或未提供原因，默认等待"},
            )

            initial_action = initial_result.get("action", "wait")
            initial_reason = initial_result.get("reason", "LLM未提供原因，默认等待")

            # 检查是否需要进行结束对话决策 ---
            if initial_action == "end_conversation":
                logger.info(f"[私聊][{self.private_name}]初步规划结束对话，进入告别决策...")

                # 使用 end_decision section
                end_decision_prompt = prompt_manager.format_prompt(
                    "chat.private.pfc.action_decision.end_decision",
                    persona_text=persona_text,
                    chat_history_text=chat_history_text,
                )

                logger.debug(
                    f"[私聊][{self.private_name}]发送到LLM的结束决策提示词:\n------\n{end_decision_prompt}\n------"
                )
                try:
                    end_content, _ = await self.llm.generate_response_async(end_decision_prompt)  # 再次调用LLM
                    logger.debug(f"[私聊][{self.private_name}]LLM (结束决策) 原始返回内容: {end_content}")

                    # 解析结束决策的JSON
                    end_success, end_result = get_items_from_json(
                        end_content,
                        self.private_name,
                        "say_bye",
                        "reason",
                        default_values={"say_bye": "no", "reason": "结束决策LLM返回格式错误，默认不告别"},
                        required_types={"say_bye": str, "reason": str},  # 明确类型
                    )

                    say_bye_decision = end_result.get("say_bye", "no").lower()  # 转小写方便比较
                    end_decision_reason = end_result.get("reason", "未提供原因")

                    if end_success and say_bye_decision == "yes":
                        # 决定要告别，返回新的 'say_goodbye' 动作
                        logger.info(
                            f"[私聊][{self.private_name}]结束决策: yes, 准备生成告别语. 原因: {end_decision_reason}"
                        )
                        # 注意：这里的 reason 可以考虑拼接初始原因和结束决策原因，或者只用结束决策原因
                        final_action = "say_goodbye"
                        final_reason = f"决定发送告别语。决策原因: {end_decision_reason} (原结束理由: {initial_reason})"
                        return final_action, final_reason
                    else:
                        # 决定不告别 (包括解析失败或明确说no)
                        logger.info(
                            f"[私聊][{self.private_name}]结束决策: no, 直接结束对话. 原因: {end_decision_reason}"
                        )
                        # 返回原始的 'end_conversation' 动作
                        final_action = "end_conversation"
                        final_reason = initial_reason  # 保持原始的结束理由
                        return final_action, final_reason

                except Exception as end_e:
                    logger.error(f"[私聊][{self.private_name}]调用结束决策LLM或处理结果时出错: {str(end_e)}")
                    # 出错时，默认执行原始的结束对话
                    logger.warning(f"[私聊][{self.private_name}]结束决策出错，将按原计划执行 end_conversation")
                    return "end_conversation", initial_reason  # 返回原始动作和原因

            else:
                action = initial_action
                reason = initial_reason

                # 验证action类型 (保持不变)
                valid_actions = [
                    "direct_reply",
                    "send_new_message",
                    "fetch_knowledge",
                    "wait",
                    "listening",
                    "rethink_goal",
                    "end_conversation",  # 仍然需要验证，因为可能从上面决策后返回
                    "block_and_ignore",
                    "say_goodbye",  # 也要验证这个新动作
                ]
                if action not in valid_actions:
                    logger.warning(f"[私聊][{self.private_name}]LLM返回了未知的行动类型: '{action}'，强制改为 wait")
                    reason = f"(原始行动'{action}'无效，已强制改为wait) {reason}"
                    action = "wait"

                logger.info(f"[私聊][{self.private_name}]规划的行动: {action}")
                logger.info(f"[私聊][{self.private_name}]行动原因: {reason}")
                return action, reason

        except Exception as e:
            # 外层异常处理保持不变
            logger.error(f"[私聊][{self.private_name}]规划行动时调用 LLM 或处理结果出错: {str(e)}")
            return "wait", f"行动规划处理中发生错误，暂时等待: {str(e)}"
