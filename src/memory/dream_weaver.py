"""
DreamWeaver — 梦呓编织者 (Phase 3.3)

从 NoisePool 中扫描被过滤的"噪音"片段，使用 LLM 发现其中的有趣关联、
矛盾或创意火花，生成低置信度的"梦呓洞见"存入 InsightPool。

运行频率: 每周一次（作为 DreamTask 每周周期的一部分）
"""

from __future__ import annotations

import json
import datetime
from typing import Any, Optional

from src.common.logger import get_logger
from src.config.config import model_config
from src.llm_models.utils_model import LLMRequest
from src.memory.schema import InsightPool, NoisePool, memory_db
from src.memory.store import MemoryStore

logger = get_logger("memory.weaver")

# 单次编织最少需要素材条目数（不足则跳过）
_MIN_WEAVE_ENTRIES: int = 10
# 单次编织最多处理的噪声条目数
_MAX_WEAVE_ENTRIES: int = 20
# 提示词中单条噪声内容的最大字符数，用于控制总提示词长度
_MAX_CONTENT_CHARS: int = 80
# 梦呓洞见默认置信度
_DEFAULT_INSIGHT_CONFIDENCE: float = 0.4


def _escape_prompt_data(text: Any) -> str:
    """转义放入 XML 风格提示块的数据内容。"""
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class DreamWeaver:
    """梦呓编织者 — 从噪声中发现诗意

    扫描噪声池，通过 LLM 发现噪声片段之间的有趣关联或矛盾，
    生成富有诗意的"梦呓洞见"并持久化到 InsightPool。

    Attributes:
        _store: MemoryStore 实例
        _noise_retention_hours: 噪声保留时间窗口（小时），
                                只处理此窗口内产生的噪声条目
        _llm_request: LLM 请求实例（延迟初始化）
    """

    def __init__(
        self,
        store: MemoryStore,
        noise_retention_hours: int = 72,
    ):
        """初始化 DreamWeaver

        Args:
            store: MemoryStore 实例
            noise_retention_hours: 只处理最近 N 小时内产生的噪声（默认 72）
        """
        self._store = store
        self._noise_retention_hours = noise_retention_hours
        self._llm_request: Optional[LLMRequest] = None

    # ── 主方法 ──────────────────────────────────────────────────────────

    async def weave(self) -> list[dict[str, Any]]:
        """执行一次梦呓编织

        流程:
        1. 查询 NoisePool 中 retention 窗口内的条目（最多 50 条）
        2. 如果少于 10 条则跳过（素材不足）
        3. 取最多 _MAX_WEAVE_ENTRIES 条，构建 LLM 提示词
        4. 调用 LLM 生成创意洞见
        5. 解析 LLM 响应，写入 InsightPool
        6. 返回生成的洞见列表

        Returns:
            list[dict]: 生成的洞见列表，
                        每项包含 insight/mood/noise_sources 字段
        """
        # 1. 查询噪声池
        entries = self._query_noise_entries()
        if not entries:
            logger.debug("洞见编织: 无可用噪声素材，跳过")
            return []

        if len(entries) < _MIN_WEAVE_ENTRIES:
            logger.info(
                "洞见编织: 噪声素材不足 (%d < %d)，跳过",
                len(entries),
                _MIN_WEAVE_ENTRIES,
            )
            return []

        # 2. 取子集用于 LLM 提示词
        weave_entries = entries[:_MAX_WEAVE_ENTRIES]
        logger.info(
            "洞见编织: 加载 %d 条噪声素材 (窗口 %d 小时，共 %d 条可用)",
            len(weave_entries),
            self._noise_retention_hours,
            len(entries),
        )

        # 3. 构建 LLM 提示词
        prompt = self._build_weave_prompt(weave_entries)

        # 4. 调用 LLM
        insights_raw = await self._call_llm(prompt)
        if not insights_raw:
            logger.debug("洞见编织: LLM 未产生洞见")
            return []

        # 5. 解析 LLM 响应
        insights = self._parse_weave_response(insights_raw)
        if not insights:
            logger.debug("洞见编织: 解析 LLM 响应后无有效洞见")
            return []

        # 6. 写入 InsightPool
        saved_insights: list[dict[str, Any]] = []
        for insight in insights:
            try:
                noise_sources = insight.get("noise_sources", [])
                source_atom_ids = [str(entries[i - 1].id) for i in noise_sources if 1 <= i <= len(entries)]
                with memory_db:
                    InsightPool.create(
                        content=insight["insight"],
                        source_atoms=json.dumps(source_atom_ids, ensure_ascii=False),
                        agent_name="dream_weaver",
                        confidence=insight.get("confidence", _DEFAULT_INSIGHT_CONFIDENCE),
                    )
                saved_insights.append(insight)
            except Exception as e:
                logger.warning("洞见编织: 写入 InsightPool 失败: %s", e)

        logger.info("洞见编织: 生成 %d 条洞见", len(saved_insights))
        return saved_insights

    # ── 噪声查询 ─────────────────────────────────────────────────────

    def _query_noise_entries(self) -> list[NoisePool]:
        """查询噪声池中 retention 窗口内的条目

        按 created_at 升序排列，最多返回 50 条。

        Returns:
            NoisePool 实例列表
        """
        try:
            cutoff = datetime.datetime.now() - datetime.timedelta(
                hours=self._noise_retention_hours,
            )
            with memory_db:
                return list(
                    NoisePool.select()
                    .where(NoisePool.created_at >= cutoff)
                    .order_by(NoisePool.created_at.asc())
                    .limit(50)
                )
        except Exception as e:
            logger.error("查询噪声池失败: %s", e)
            return []

    # ── 提示词构建 ──────────────────────────────────────────────────

    @staticmethod
    def _build_weave_prompt(entries: list[NoisePool]) -> str:
        """构建 LLM 提示词

        将噪声片段格式化为编号列表，
        引导 LLM 发现其中的关联、矛盾或创意灵感。

        Args:
            entries: 噪声条目列表（建议不超过 20 条以控制提示词长度）

        Returns:
            LLM 提示词字符串
        """
        lines: list[str] = []
        for i, entry in enumerate(entries, 1):
            source = _escape_prompt_data(entry.source_scene or "unknown")
            content = _escape_prompt_data(entry.content or "")[:_MAX_CONTENT_CHARS]
            lines.append(f"{i}. {content} (来源: {source})")

        entries_text = "\n".join(lines)

        prompt = f"""你是记忆系统的噪声审阅器。下面是被过滤进 NoisePool 的片段，它们默认不是可靠记忆。

<NOISE_POOL>
{entries_text}
</NOISE_POOL>

任务：
从噪声片段中寻找 1-3 条“弱洞见”。弱洞见只能是低置信度的观察或假设，用于以后人工/系统复核，不能写成确定事实。

必须遵守：
1. 每条洞见必须由至少两个噪声编号共同支持，noise_sources 至少包含 2 个编号
2. 不要补全上下文，不要编造人物关系、长期偏好、稳定习惯或事件结论
3. 如果只是随机词句、寒暄、表情反应、孤立玩笑，返回 []
4. insight 用一句中文写清楚“可能/似乎/像是”的弱关联，不要写成事实
5. confidence 只能在 0.2 到 0.6 之间；越像巧合越低

只返回严格 JSON 数组，不要 markdown、注释或额外说明。格式：
[
  {{
    "insight": "可能存在的弱关联",
    "mood": "情绪标签",
    "confidence": 0.4,
    "noise_sources": [1, 3]
  }}
]
如果没有至少两个片段支持的弱关联，返回 []。"""
        return prompt

    # ── LLM 调用 ────────────────────────────────────────────────────

    async def _call_llm(self, prompt: str) -> str:
        """调用 LLM 生成洞见

        使用 LLMRequest 异步调用，配置 temperature=0.7 以获取创意输出。
        任何异常时优雅降级，返回空字符串。

        Args:
            prompt: LLM 提示词

        Returns:
            LLM 响应文本，失败返回空字符串
        """
        try:
            if self._llm_request is None:
                task_config = getattr(
                    model_config.model_task_config,
                    "memory_weaver",
                    None,
                )
                if task_config is None:
                    task_config = model_config.model_task_config.utils
                    logger.warning(
                        "任务 'memory_weaver' 未在 model_config 中找到，回退到 'utils' 任务",
                    )
                self._llm_request = LLMRequest(
                    model_set=task_config,
                    request_type="memory_weaver",
                )

            content, _ = await self._llm_request.generate_response_async(
                prompt=prompt,
                temperature=0.7,
                max_tokens=1024,
            )
            return content.strip()
        except Exception as e:
            logger.warning("洞见编织 LLM 调用失败: %s", e)
            return ""

    # ── 响应解析 ────────────────────────────────────────────────────

    @staticmethod
    def _parse_weave_response(response: str) -> list[dict[str, Any]]:
        """解析 LLM 返回的 JSON 洞见列表

        支持纯 JSON 和 markdown 代码块两种格式。
        如果解析失败，尝试从文本中提取 JSON 数组。

        Args:
            response: LLM 原始响应文本

        Returns:
            解析后的洞见字典列表，结构：
            [{"insight": "...", "mood": "...", "noise_sources": [1, 2]}]
        """
        if not response:
            return []

        text = response.strip()

        # 尝试提取 markdown json 代码块
        if "```json" in text:
            start = text.find("```json") + 7
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()
        elif "```" in text:
            start = text.find("```") + 3
            end = text.find("```", start)
            if end > start:
                text = text[start:end].strip()

        # 尝试直接解析 JSON
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return _validate_insights(parsed)
            if isinstance(parsed, dict) and "insight" in parsed:
                return _validate_insights([parsed])
            return []
        except json.JSONDecodeError:
            pass

        # 回退: 从文本中提取 JSON 数组
        try:
            arr_start = text.find("[")
            arr_end = text.rfind("]")
            if 0 <= arr_start < arr_end:
                parsed = json.loads(text[arr_start : arr_end + 1])
                if isinstance(parsed, list):
                    return _validate_insights(parsed)
        except (json.JSONDecodeError, IndexError):
            pass

        logger.warning(
            "洞见编织: 解析 LLM 响应失败, 响应前200字符: %s",
            text[:200],
        )
        return []


def _validate_insights(insights: list[Any]) -> list[dict[str, Any]]:
    """过滤并校验洞见列表

    保留满足以下条件的条目:
      - 包含 'insight' 键且内容有实际文本（不只标点/空白）
      - noise_sources 是至少包含两个正整数的列表
      - confidence 被约束在 0.2~0.6 的低置信度区间

    Args:
        insights: 原始解析结果

    Returns:
        校验后的有效洞见列表
    """
    valid: list[dict[str, Any]] = []
    for item in insights:
        if not isinstance(item, dict) or "insight" not in item:
            continue
        insight_text = str(item.get("insight", "")).strip()
        if not insight_text or not any(c.isalpha() for c in insight_text):
            logger.debug(f"洞见语义校验失败: 无有效文本 | insight={insight_text!r}")
            continue
        sources = item.get("noise_sources", [])
        if not isinstance(sources, list):
            logger.debug("洞见语义校验失败: noise_sources 不是列表")
            continue
        sources = [s for s in sources if isinstance(s, int) and s > 0]
        if len(sources) < 2:
            logger.debug("洞见语义校验失败: noise_sources 少于两个")
            continue
        item["noise_sources"] = sources

        confidence = item.get("confidence", _DEFAULT_INSIGHT_CONFIDENCE)
        if not isinstance(confidence, (int, float)):
            confidence = _DEFAULT_INSIGHT_CONFIDENCE
        item["confidence"] = max(0.2, min(0.6, float(confidence)))
        valid.append(item)
    return valid
