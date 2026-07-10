"""
第2层记忆编码器 — LLM 驱动的批量记忆原子提取管道

从累积的对话消息中批量提取记忆原子（情景/事实/关系/偏好），
集成第1层话题摘要作为上下文，输出结构化的记忆候选供第3层写入。

设计定位:
  Layer 0: 原始消息归档（MessageArchiver）
  Layer 1: 纯算法话题摘要（GroupTopicSummarizer / PrivateChatSummarizer）
  Layer 2: LLM 驱动的结构化记忆提取（本模块）
  Layer 3: 记忆持久化写入 + 向量检索（MemoryWriter / MemoryRetriever）

工作流程:
  1. ingest_message() → 按 stream_id 缓存消息
  2. 达到触发阈值（消息数 OR 时间间隔）时自动调用 encode_batch()
  3. encode_batch() 从第1层获取话题摘要，构建 LLM 提取提示
  4. LLM 返回结构化的记忆原子候选
  5. parse 后返回 list of (content, atom_type, detail_dict) 元组
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from src.common.logger import get_logger
from src.common.prompt_loader import load_prompt
from src.memory.types import BufferMessage
from src.config.config import model_config
from src.llm_models.utils_model import LLMRequest
from src.memory.atom import AtomType
from src.memory.layer1_summarizer import GroupTopicSummarizer, PrivateChatSummarizer
from src.memory.prompt_integration import neutralize_prompt_boundaries
from src.memory.store import MemoryStore

logger = get_logger("memory.layer2")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 未配置专用任务时的 fallback 任务名
DEFAULT_ENCODING_TASK = "memory_encoder"

# 单次编码最大发送给 LLM 的消息数（超出则截取最近 N 条）
MAX_MESSAGES_PER_BATCH = 30

# LLM JSON 响应最大解析尝试次数
MAX_LLM_PARSE_ATTEMPTS = 2

# 单条原子 content 的最大字符数
MAX_ATOM_CONTENT_LENGTH = 200

# 单条原子允许关联的实体数量和长度上限
MAX_ENTITIES_PER_ATOM = 12
MAX_ENTITY_LENGTH = 200

# LLM detail 字段上限，避免异常输出导致画像/详情字段膨胀
MAX_DETAIL_TEXT_LENGTH = 300
MAX_DETAIL_LIST_ITEMS = 12

# 内部元数据键：EncodingPipeline 用它限制画像更新目标，避免信任 LLM 伪造 entities
SOURCE_USER_IDS_DETAIL_KEY = "_source_user_ids"

# ---------------------------------------------------------------------------
# EncodingBuffer — 单流编码缓冲区
# ---------------------------------------------------------------------------


@dataclass
class EncodingBuffer:
    """单流编码缓冲区 — 为每个聊天流维护待编码的消息暂存区

    Attributes:
        stream_id: 聊天流 ID（群号 / 用户ID）
        stream_type: 流类型（group_chat / private_chat）
        messages: 累积的消息列表，每条含 user_id / speaker / content / timestamp
        last_trigger_time: 上次触发编码的 time.time() 值
        message_count_since_trigger: 上次触发后累积的消息数量
    """

    stream_id: str
    stream_type: str = "group_chat"
    messages: list[BufferMessage] = field(default_factory=list)
    last_trigger_time: float = field(default_factory=time.time)
    message_count_since_trigger: int = 0
    max_buffer_size: int = 100

    def add_message(
        self,
        user_id: str,
        speaker: str,
        content: str,
        timestamp: float,
        message_id: Optional[str] = None,
    ) -> bool:
        """添加一条消息到缓冲区"""
        normalized_message_id = str(message_id or "").strip()
        if normalized_message_id and any(msg.get("message_id") == normalized_message_id for msg in self.messages):
            logger.debug(
                "EncodingBuffer 跳过重复消息",
                stream_id=self.stream_id,
                message_id=normalized_message_id,
            )
            return False

        self.messages.append(
            {
                **({"message_id": normalized_message_id} if normalized_message_id else {}),
                "user_id": user_id,
                "speaker": speaker,
                "content": content,
                "timestamp": timestamp,
            }
        )
        self.message_count_since_trigger += 1

        if len(self.messages) > self.max_buffer_size:
            overflow_count = len(self.messages) - self.max_buffer_size
            logger.warning(
                f"EncodingBuffer overflow: stream={self.stream_id}, "
                f"dropped={overflow_count}, remaining={self.max_buffer_size}",
            )
            self.messages = self.messages[-self.max_buffer_size :]
        return True

    def clear(self) -> None:
        """清空缓冲区但保留流状态"""
        self.messages.clear()
        self.last_trigger_time = time.time()
        self.message_count_since_trigger = 0

    def __len__(self) -> int:
        return len(self.messages)


# ---------------------------------------------------------------------------
# BatchEncoder — 批量记忆编码器
# ---------------------------------------------------------------------------


class BatchEncoder:
    """批量记忆编码器 — 消息累积 → 阈值触发 → LLM 提取 → 返回原子候选

    Args:
        store: MemoryStore 实例
        trigger_count: 累积多少条消息后触发编码（默认 10）
        trigger_seconds: 距离上次触发超过多少秒后强制触发（默认 300）
        task_name: model_config 中的任务名称（默认 "utils"）
        max_messages_per_batch: 单次编码最多发送给 LLM 的消息数
    """

    MAX_BUFFER_SIZE: int = 100

    def __init__(
        self,
        store: MemoryStore,
        trigger_count: int = 10,
        trigger_seconds: int = 300,
        task_name: str = DEFAULT_ENCODING_TASK,
        max_messages_per_batch: int = MAX_MESSAGES_PER_BATCH,
    ) -> None:
        self.store = store
        self.trigger_count = trigger_count
        self.trigger_seconds = trigger_seconds
        self.task_name = task_name
        self.max_messages_per_batch = max_messages_per_batch

        # 按 stream_id 索引的编码缓冲区
        self.buffers: dict[str, EncodingBuffer] = {}

        # 第1层话题摘要器（群聊用）
        self.group_summarizer = GroupTopicSummarizer()

        # 第1层渐进式摘要器（私聊用）
        self.private_summarizer = PrivateChatSummarizer()

        # LLM 请求实例（延迟初始化）
        self._llm_request: Optional[LLMRequest] = None

        logger.info(
            f"BatchEncoder 初始化完成 | trigger_count={trigger_count} "
            f"trigger_seconds={trigger_seconds} task_name={task_name}",
        )

    # ── 消息摄取 ────────────────────────────────────────────────────

    async def ingest_message(
        self,
        stream_id: str,
        user_id: str,
        speaker: str,
        content: str,
        timestamp: Optional[datetime] = None,
        message_id: Optional[str] = None,
    ) -> None:
        """摄取一条消息到缓冲区

        消息会同时被送入第1层摘要器（群聊话题分配 / 私聊渐进式摘要）。
        调用方负责在外部判断 stream_type。

        Args:
            stream_id: 聊天流 ID
            user_id: 发送者用户 ID
            speaker: 发送者显示名称
            content: 消息文本内容
            timestamp: 消息时间戳（默认当前时间）
            message_id: 原始消息 ID（可选，用于缓冲去重）
        """
        ts = timestamp.timestamp() if timestamp else time.time()

        # 确保缓冲区存在
        if stream_id not in self.buffers:
            # 根据 stream_id 特征推断类型（外部也可先调用 set_stream_type）
            inferred_type = "private_chat" if "_private_" in stream_id else "group_chat"
            self.buffers[stream_id] = EncodingBuffer(
                stream_id=stream_id,
                stream_type=inferred_type,
                max_buffer_size=self.MAX_BUFFER_SIZE,
            )

        buf = self.buffers[stream_id]
        added = buf.add_message(user_id=user_id, speaker=speaker, content=content, timestamp=ts, message_id=message_id)
        if not added:
            return

        # 同步送入第1层摘要器
        if buf.stream_type == "group_chat":
            await self.group_summarizer.add_message_async(
                stream_id=stream_id,
                message_text=content,
                user_id=user_id,
                timestamp=ts,
                speaker=speaker,
            )
        else:
            self.private_summarizer.append_exchange(
                stream_id=stream_id,
                speaker=speaker,
                content=content,
                timestamp=ts,
            )

        logger.debug(
            f"消息已摄取 | stream={stream_id} user={user_id} buffer_size={len(buf)} trigger_count={self.trigger_count}",
        )

    def set_stream_type(self, stream_id: str, stream_type: str) -> None:
        """显式设置流的类型

        Args:
            stream_id: 聊天流 ID
            stream_type: group_chat / private_chat
        """
        if stream_id in self.buffers:
            self.buffers[stream_id].stream_type = stream_type
        else:
            self.buffers[stream_id] = EncodingBuffer(
                stream_id=stream_id,
                stream_type=stream_type,
                max_buffer_size=self.MAX_BUFFER_SIZE,
            )

    # ── 触发检测 ────────────────────────────────────────────────────

    def should_trigger(self, stream_id: str) -> bool:
        """判断指定流是否满足编码触发条件

        两个条件之一满足即触发:
          1. 累积消息数 >= trigger_count
          2. 距离上次触发超过 trigger_seconds 秒且缓冲区非空

        Args:
            stream_id: 聊天流 ID

        Returns:
            是否应触发编码
        """
        buf = self.buffers.get(stream_id)
        if buf is None or not buf.messages:
            return False

        # 条件1: 消息数阈值
        if buf.message_count_since_trigger >= self.trigger_count:
            return True

        # 条件2: 时间阈值
        if time.time() - buf.last_trigger_time >= self.trigger_seconds:
            return True

        return False

    def get_ready_streams(self) -> list[str]:
        """获取所有满足触发条件的流 ID 列表

        Returns:
            可触发编码的 stream_id 列表
        """
        return [sid for sid in self.buffers if self.should_trigger(sid)]

    # ── 批量编码 ────────────────────────────────────────────────────

    async def encode_batch(
        self,
        stream_id: str,
        force: bool = False,
    ) -> list[tuple[str, AtomType, dict[str, Any]]]:
        """对指定流的累计消息执行批量编码

        流程:
          1. 获取缓冲区消息（截取最近 N 条）
          2. 从第1层获取当前话题摘要作为上下文
          3. 构建 LLM 编码提示
          4. 调用 LLM 提取结构化记忆
          5. 解析 LLM 输出为 (content, atom_type, detail) 元组列表
          6. 清空缓冲区

        Args:
            stream_id: 聊天流 ID
            force: 强制编码（跳过 should_trigger 检查）

        Returns:
            list of (content, atom_type, detail_dict) 元组
        """
        buf = self.buffers.get(stream_id)
        if buf is None:
            logger.warning(f"编码跳过：流不存在 | stream={stream_id}")
            return []

        if not buf.messages:
            logger.debug(f"编码跳过：缓冲区为空 | stream={stream_id}")
            return []

        if not force and not self.should_trigger(stream_id):
            logger.debug(f"编码跳过：未满足触发条件 | stream={stream_id}")
            return []

        logger.info(
            f"开始编码 | stream={stream_id} type={buf.stream_type} messages={len(buf)}",
        )
        start_time = time.time()

        # 1. 截取最近 N 条消息
        messages = buf.messages[-self.max_messages_per_batch :]

        # 2. 获取第1层话题摘要
        topic_summary = self._get_topic_summary(stream_id, buf.stream_type)

        # 3. 构建编码提示
        prompt = self._build_encoding_prompt(messages, topic_summary)

        logger.info(
            "开始批量编码",
            stream_id=stream_id,
            msg_count=len(messages),
            prompt_len=len(prompt),
        )

        # 4. 调用 LLM
        try:
            llm_output = await self._call_llm(prompt)
        except Exception as exc:
            logger.error(
                f"LLM 编码调用失败 | stream={stream_id} error={exc}",
            )
            # 失败时不清空缓冲区，允许下次重试
            return []

        # 5. 解析 LLM 输出
        extracted = self._parse_llm_extraction(llm_output)
        if extracted is None:
            logger.warning("LLM 编码输出解析失败，保留缓冲区等待下次重试 | stream=%s", stream_id)
            return []

        source_user_ids = self._source_user_ids(messages)
        if source_user_ids:
            for _, _, detail in extracted:
                detail[SOURCE_USER_IDS_DETAIL_KEY] = list(source_user_ids)

        # 6. 清空缓冲区
        buf.clear()

        elapsed = time.time() - start_time
        logger.info(
            "批量编码完成",
            stream_id=stream_id,
            atom_count=len(extracted),
            time_ms=round(elapsed * 1000),
        )
        logger.info(
            f"编码完成 | stream={stream_id} extracted={len(extracted)}",
        )
        return extracted

    async def encode_all_ready(self) -> dict[str, list[tuple[str, AtomType, dict[str, Any]]]]:
        """对所有满足触发条件的流执行编码

        Returns:
            stream_id → 提取结果列表 的映射字典
        """
        results: dict[str, list[tuple[str, AtomType, dict[str, Any]]]] = {}
        for stream_id in self.get_ready_streams():
            atoms = await self.encode_batch(stream_id)
            if atoms:
                results[stream_id] = atoms
        return results

    # ── 提示构建 ────────────────────────────────────────────────────

    def _build_encoding_prompt(
        self,
        messages: list[BufferMessage],
        topic_summary: str,
    ) -> str:
        """构建 LLM 编码提示

        Args:
            messages: 消息列表（每条含 user_id / speaker / content / timestamp）
            topic_summary: 第1层提供的话题摘要上下文

        Returns:
            完整的 LLM 提示字符串
        """
        # 格式化消息
        lines: list[str] = []
        for msg in messages:
            speaker = neutralize_prompt_boundaries(str(msg.get("speaker", msg.get("user_id", "unknown"))))
            user_id = neutralize_prompt_boundaries(str(msg.get("user_id", "unknown")))
            content = neutralize_prompt_boundaries(str(msg.get("content", "")))
            lines.append(f"[speaker={speaker} user_id={user_id}]: {content}")

        conversation_text = "\n".join(lines)
        topic_summary = neutralize_prompt_boundaries(topic_summary or "（无）")

        return load_prompt(
            "memory_atom_extraction",
            topic_summary=topic_summary,
            conversation_text=conversation_text,
        )

    # ── LLM 调用 ────────────────────────────────────────────────────

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM 获取编码结果

        使用 model_config 中配置的任务来发起 LLM 请求。

        Args:
            prompt: 完整的编码提示

        Returns:
            LLM 响应文本

        Raises:
            RuntimeError: LLM 调用失败时抛出
        """
        if self._llm_request is None:
            task_config = getattr(model_config.model_task_config, self.task_name, None)
            if task_config is None:
                # fallback 到 utils
                task_config = model_config.model_task_config.utils
                logger.warning(
                    f"任务 '{self.task_name}' 未在 model_config 中找到，回退到 'utils' 任务",
                )
            self._llm_request = LLMRequest(
                model_set=task_config,
                request_type="memory_encoder",
            )

        logger.debug("开始LLM编码调用", prompt_len=len(prompt))

        content, resp_tuple = await self._llm_request.generate_response_async(
            prompt=prompt,
            temperature=0.3,
            max_tokens=4096,
        )
        model_name = resp_tuple[1] if resp_tuple else None
        logger.debug(
            "LLM编码调用完成",
            response_len=len(content),
            model=model_name if model_name else "unknown",
        )
        return content.strip()

    # ── LLM 输出解析 ────────────────────────────────────────────────

    def _parse_llm_extraction(
        self,
        llm_response: str,
    ) -> Optional[list[tuple[str, AtomType, dict[str, Any]]]]:
        """解析 LLM 返回的结构化提取结果

        支持纯 JSON 和 markdown 代码块两种格式。

        Args:
            llm_response: LLM 原始响应文本

        Returns:
            list of (content, atom_type, detail_dict) 元组
        """
        if not llm_response:
            logger.warning("LLM 返回空响应，无可提取的记忆")
            return None

        # 尝试直接解析
        parsed = self._try_parse_json(llm_response)

        # 若失败，尝试提取 markdown 代码块中的 JSON
        if parsed is None:
            extracted_block = self._extract_json_block(llm_response)
            if extracted_block:
                parsed = self._try_parse_json(extracted_block)

        if parsed is None:
            logger.warning(
                f"LLM 响应无法解析为 JSON | response_preview={llm_response[:200]}",
            )
            return None

        if not isinstance(parsed, list):
            logger.warning(
                f"LLM 响应不是 JSON 数组 | type={type(parsed).__name__}",
            )
            return None

        # 验证并转换每条原子
        result: list[tuple[str, AtomType, dict[str, Any]]] = []
        for idx, item in enumerate(parsed):
            try:
                atom_tuple = self._validate_atom_item(item)
                if atom_tuple is not None:
                    result.append(atom_tuple)
            except (ValueError, TypeError) as exc:
                logger.debug(
                    f"跳过无效原子条目[{idx}] | error={exc} item={item}",
                )
                continue

        return result

    @staticmethod
    def _try_parse_json(text: str) -> Optional[Any]:
        """尝试解析 JSON 字符串，失败返回 None"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_json_block(text: str) -> Optional[str]:
        """从 markdown 代码块中提取 JSON 字符串

        支持 ```json ... ``` 和 ``` ... ``` 两种格式。
        """
        # 尝试 ```json ... ```
        start_marker = "```json"
        start_idx = text.find(start_marker)
        if start_idx >= 0:
            content_start = start_idx + len(start_marker)
            end_marker = "```"
            end_idx = text.find(end_marker, content_start)
            if end_idx >= 0:
                return text[content_start:end_idx].strip()

        # 尝试 ``` ... ``` (无语言标识)
        start_marker = "```"
        start_idx = text.find(start_marker)
        if start_idx >= 0:
            content_start = start_idx + len(start_marker)
            end_marker = "```"
            end_idx = text.find(end_marker, content_start)
            if end_idx >= 0:
                return text[content_start:end_idx].strip()

        return None

    @staticmethod
    def _safe_text(value: Any, max_length: int = MAX_DETAIL_TEXT_LENGTH) -> str:
        """把 LLM 输出收敛为短文本；复杂对象不做字符串化入库。"""
        if value is None or not isinstance(value, (str, int, float, bool)):
            return ""
        return str(value).strip()[:max_length]

    @staticmethod
    def _safe_str_list(
        value: Any,
        max_items: int = MAX_DETAIL_LIST_ITEMS,
        max_length: int = MAX_DETAIL_TEXT_LENGTH,
    ) -> list[str]:
        """把 LLM 输出收敛为去重短字符串列表。"""
        if not isinstance(value, list):
            return []

        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = BatchEncoder._safe_text(item, max_length)
            if not text or text in seen:
                continue
            result.append(text)
            seen.add(text)
            if len(result) >= max_items:
                break
        return result

    @staticmethod
    def _source_user_ids(messages: list[BufferMessage]) -> list[str]:
        """提取本批真实消息里的 user_id，供画像更新做白名单。"""
        user_ids: list[str] = []
        seen: set[str] = set()
        for msg in messages:
            user_id = BatchEncoder._safe_text(msg.get("user_id"), MAX_ENTITY_LENGTH)
            if not user_id or user_id in seen:
                continue
            user_ids.append(user_id)
            seen.add(user_id)
        return user_ids

    def _validate_atom_item(
        self,
        item: Any,
    ) -> Optional[tuple[str, AtomType, dict[str, Any]]]:
        """验证并规范化单条原子条目

        包含两层校验:
          1. 结构校验 — 字段类型、格式正确性
          2. 语义校验 — 内容是否有意义、detail 是否与类型匹配

        Args:
            item: 解析后的 JSON 条目（应为 dict）

        Returns:
            (content, atom_type, detail) 元组，无效则返回 None
        """
        if not isinstance(item, dict):
            return None

        # 提取 content
        content = self._safe_text(item.get("content", ""), MAX_ATOM_CONTENT_LENGTH)
        if not content:
            return None

        # 提取 atom_type
        raw_type = self._safe_text(item.get("atom_type", ""), 40).lower()
        try:
            atom_type = AtomType(raw_type)
        except ValueError:
            logger.debug(f"无效的 atom_type: {raw_type}")
            return None

        # 提取 importance
        importance = item.get("importance", 0.5)
        if not isinstance(importance, (int, float)):
            importance = 0.5
        importance = max(0.0, min(1.0, float(importance)))

        # 提取 entities
        entities = self._safe_str_list(
            item.get("entities", []),
            max_items=MAX_ENTITIES_PER_ATOM,
            max_length=MAX_ENTITY_LENGTH,
        )

        # 提取 detail
        detail = item.get("detail", {})
        if not isinstance(detail, dict):
            detail = {}

        # 按类型补充默认 detail，并保留通用元数据供 EncodingPipeline 构建 MemoryAtom。
        detail = self._normalize_detail(atom_type, detail, entities)
        detail["entities"] = entities
        detail["importance"] = importance

        if not self._semantic_validate(content, atom_type, detail, entities):
            logger.debug(
                f"语义校验不通过 | type={atom_type} content={content!r} entities={entities} detail={detail}",
            )
            return None

        # 组装返回元组（调用方可通过 store.insert_atom 再补全字段）
        return (content, atom_type, detail)

    def _semantic_validate(
        self,
        content: str,
        atom_type: AtomType,
        detail: dict[str, Any],
        entities: list[str],
    ) -> bool:
        """语义校验 — 验证记忆原子内容在语义上是否合理

        Args:
            content: 原子内容（已截断到 MAX_ATOM_CONTENT_LENGTH）
            atom_type: 原子类型
            detail: 规范化后的 detail 字典
            entities: 实体列表

        Returns:
            语义上是否有效
        """
        if not any(c.isalpha() for c in content):
            logger.debug(f"content 无有效文本字符 | content={content!r}")
            return False

        if any(not isinstance(e, str) or not e.strip() for e in entities):
            logger.debug(f"entities 包含空项 | entities={entities}")
            return False
        if len(entities) > MAX_ENTITIES_PER_ATOM:
            logger.debug("entities 数量超限")
            return False
        if any(len(e) > MAX_ENTITY_LENGTH for e in entities):
            logger.debug("entities 包含超长项")
            return False

        if atom_type == AtomType.FACTUAL:
            if not detail.get("attr_name", "").strip() or not detail.get("attr_value", "").strip():
                logger.debug(f"factual 缺少 attr_name 或 attr_value | detail={detail}")
                return False

        elif atom_type == AtomType.PREFERENCE:
            if not detail.get("attr_name", "").strip():
                logger.debug(f"preference 缺少 attr_name | detail={detail}")
                return False

        elif atom_type == AtomType.EPISODIC:
            participants = detail.get("participants", [])
            has_participants = bool(participants)
            has_event_keywords = any(kw in content for kw in ("了", "过", "在", "说", "去", "来", "看", "做"))
            if not has_participants and not has_event_keywords:
                logger.debug(
                    f"episodic 缺少参与者与事件特征 | participants={participants}",
                )
                return False

        return True

    @staticmethod
    def _normalize_detail(
        atom_type: AtomType,
        detail: dict[str, Any],
        entities: list[str],
    ) -> dict[str, Any]:
        """按记忆类型规范化 detail 字段

        Args:
            atom_type: 记忆原子类型
            detail: 原始 detail 字典
            entities: 实体列表

        Returns:
            规范化后的 detail 字典
        """
        if atom_type == AtomType.EPISODIC:
            participants = BatchEncoder._safe_str_list(
                detail.get("participants"),
                max_items=MAX_ENTITIES_PER_ATOM,
                max_length=MAX_ENTITY_LENGTH,
            )
            if not participants:
                participants = entities[:MAX_ENTITIES_PER_ATOM]
            return {
                "participants": participants,
                "emotion_tags": BatchEncoder._safe_str_list(detail.get("emotion_tags")),
                "sensory_tags": BatchEncoder._safe_str_list(detail.get("sensory_tags")),
                "temporal_context": BatchEncoder._safe_text(detail.get("temporal_context", "")),
            }

        elif atom_type == AtomType.FACTUAL:
            return {
                "attr_category": BatchEncoder._safe_text(detail.get("attr_category", "general"), 80) or "general",
                "attr_name": BatchEncoder._safe_text(detail.get("attr_name", ""), 120),
                "attr_value": BatchEncoder._safe_text(detail.get("attr_value", "")),
            }

        elif atom_type == AtomType.RELATIONAL:
            # 关系型记忆的内容本身描述关系，detail 可留空或包含额外字段
            return {}

        elif atom_type == AtomType.PREFERENCE:
            return {
                "attr_category": "preference",
                "attr_name": BatchEncoder._safe_text(detail.get("attr_name", ""), 120),
                "attr_value": BatchEncoder._safe_text(detail.get("attr_value", "喜欢")),
            }

        return {}

    # ── 第1层摘要集成 ─────────────────────────────────────────────

    def _get_topic_summary(
        self,
        stream_id: str,
        stream_type: str,
    ) -> str:
        """从第1层获取当前话题摘要

        Args:
            stream_id: 聊天流 ID
            stream_type: 流类型

        Returns:
            摘要文本，若无则返回空字符串
        """
        if stream_type == "group_chat":
            summaries = self.group_summarizer.get_topic_summaries(stream_id)
            if not summaries:
                return ""
            parts: list[str] = []
            for s in summaries:
                keywords = ", ".join(s.get("keywords", []))
                points = "; ".join(s.get("key_points", []))
                if keywords:
                    parts.append(f"话题关键词: {keywords}")
                if points:
                    parts.append(f"要点: {points}")
            return "\n".join(parts)
        else:
            summary_text = self.private_summarizer.get_summary(stream_id)
            return summary_text or ""

    # ── 缓冲区管理 ─────────────────────────────────────────────────

    def get_buffer(self, stream_id: str) -> Optional[EncodingBuffer]:
        """获取指定流的缓冲区

        Args:
            stream_id: 聊天流 ID

        Returns:
            EncodingBuffer 实例，或 None
        """
        return self.buffers.get(stream_id)

    def get_buffer_stats(self, stream_id: str) -> Optional[dict[str, Any]]:
        """获取指定流的缓冲区统计信息

        Args:
            stream_id: 聊天流 ID

        Returns:
            统计字典，或 None
        """
        buf = self.buffers.get(stream_id)
        if buf is None:
            return None
        return {
            "stream_id": buf.stream_id,
            "stream_type": buf.stream_type,
            "buffer_size": len(buf),
            "message_count_since_trigger": buf.message_count_since_trigger,
            "last_trigger_ago": time.time() - buf.last_trigger_time,
            "should_trigger": self.should_trigger(stream_id),
        }

    def get_all_streams(self) -> list[str]:
        """获取所有受管的流 ID

        Returns:
            stream_id 列表
        """
        return list(self.buffers.keys())

    def get_pending_streams(self) -> list[str]:
        """获取所有有待编码消息的流 ID

        Returns:
            缓冲区非空的 stream_id 列表
        """
        return [sid for sid, buf in self.buffers.items() if buf.messages]

    def remove_stream(self, stream_id: str) -> bool:
        """移除指定流的缓冲区和摘要状态

        Args:
            stream_id: 聊天流 ID

        Returns:
            是否存在并被移除
        """
        existed = stream_id in self.buffers
        self.buffers.pop(stream_id, None)
        self.group_summarizer.reset_stream(stream_id)
        self.private_summarizer.reset(stream_id)
        return existed

    def clear_all(self) -> None:
        """清空所有缓冲区（保留缓冲对象）"""
        for buf in self.buffers.values():
            buf.clear()

    def reset_all(self) -> None:
        """完全重置所有状态（清空缓冲区、摘要器、缓冲区映射）"""
        self.buffers.clear()
        self.group_summarizer = GroupTopicSummarizer()
        self.private_summarizer = PrivateChatSummarizer()

    # ── 待编码队列（用于外部遍历） ────────────────────────────────

    def iter_pending(self):
        """遍历所有有待编码消息的流

        Yields:
            (stream_id, EncodingBuffer) 元组
        """
        for sid, buf in self.buffers.items():
            if buf.messages:
                yield sid, buf
