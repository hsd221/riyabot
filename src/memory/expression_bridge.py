"""表达学习桥接 — 关联 bw_learner 与用户画像

纯启发式规则，不涉及 LLM 调用。通过分析用户的消息文本，
提取表达风格、高频短语、表情偏好和术语，写入用户画像。

使用方式:
    from src.memory.expression_bridge import ExpressionBridge, ExpressionProfile

    bridge = ExpressionBridge(profile_store)
    bridge.update_expression_profile("user_123", messages)
    context = bridge.get_expression_context("user_123")
"""

import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from statistics import median

from src.common.logger import get_logger

logger = get_logger("memory.expression")

# ---------------------------------------------------------------------------
# 表情符号检测 — 覆盖常见 Unicode 表情区段
# ---------------------------------------------------------------------------
_EMOJI_BASE = (
    "\U0001f600-\U0001f64f"  # Emoticons
    "\U0001f300-\U0001f5ff"  # Misc Symbols and Pictographs
    "\U0001f680-\U0001f6ff"  # Transport and Map
    "\U00002600-\U000027bf"  # Misc Symbols + Dingbats
    "\U0001f900-\U0001f9ff"  # Supplemental Symbols
    "\U0001fa00-\U0001fa6f"  # Chess Symbols
    "\U0001fa70-\U0001faff"  # Symbols Extended-A
)
_EMOJI_COMPONENT = f"[{_EMOJI_BASE}](?:[\ufe0e\ufe0f])?(?:[\U0001f3fb-\U0001f3ff])?"
_EMOJI_RE = re.compile(f"(?:[\U0001f1e6-\U0001f1ff]{{2}}|{_EMOJI_COMPONENT}(?:\u200d{_EMOJI_COMPONENT})*)")

_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_LATIN_TOKEN_RE = re.compile(r"[a-zA-Z0-9_\u00c0-\u024f\u0400-\u04ff]+")
_CLAUSE_SPLIT_RE = re.compile(r"[\s,，。.!！?？;；:：、~～…（）()\[\]{}<>《》“”\"'`]+")
_EXPRESSION_STOPWORDS = {
    "一个",
    "这个",
    "那个",
    "就是",
    "然后",
    "因为",
    "所以",
    "但是",
    "如果",
    "我们",
    "你们",
    "他们",
    "自己",
}
_EXPRESSION_ANALYSIS_VERSION = 2
_MAX_FAVORITE_EXPRESSIONS = 8
_MAX_ANALYZED_MESSAGES = 200
_MIN_STYLE_MESSAGES = 5

# ---------------------------------------------------------------------------
# 表达风格分类阈值
# ---------------------------------------------------------------------------
# 正式用语标记（启发式）
_FORMAL_MARKERS = {
    "因此",
    "综上所述",
    "显而易见",
    "不可否认",
    "毋庸置疑",
    "值得注意的是",
    "换言之",
    "也就是说",
    "从某种意义上说",
    "从本质上讲",
    "从宏观角度",
    "从微观层面",
}

# ---------------------------------------------------------------------------
# ExpressionProfile — 表达画像数据
# ---------------------------------------------------------------------------


@dataclass
class ExpressionProfile:
    """用户表达画像数据

    Attributes:
        user_id: 用户唯一标识
        favorite_expressions: 在多条消息中重复出现的短语
        jargon_terms: 已学习的术语/黑话
        expression_style: 表达风格分类
        emoji_preferences: 偏好的表情符号列表
        average_message_length: 平均消息长度（字符数）
        updated_at: 最后更新时间戳
    """

    user_id: str
    favorite_expressions: list[str] = field(default_factory=list)
    jargon_terms: list[str] = field(default_factory=list)
    expression_style: str = ""
    emoji_preferences: list[str] = field(default_factory=list)
    average_message_length: float = 0.0
    updated_at: float = 0.0


# ---------------------------------------------------------------------------
# ExpressionBridge — 表达学习桥接主类
# ---------------------------------------------------------------------------


class ExpressionBridge:
    """表达学习桥接器 — 从消息中提取表达特征写入用户画像

    纯启发式规则分析，不依赖 bw_learner 或 LLM。
    通过 ProfileStore 将结果持久化到 UserProfile.stats 中。
    """

    def __init__(self, profile_store) -> None:
        """初始化 ExpressionBridge

        Args:
            profile_store: ProfileStore 实例（from src.memory.user_profile import ProfileStore）
        """
        self._profile_store = profile_store

    # ── 公开接口 ─────────────────────────────────────────────────

    def update_expression_profile(self, subject, messages: list[str]) -> None:
        """分析用户最近消息，更新表达画像

        fire-and-forget 调用，异常仅记日志不抛出。

        Args:
            subject: PersonIdentity 或兼容历史数据的画像 ID
            messages: 最近消息文本列表
        """
        clean_messages = self._collect_sample_messages(subject, messages)
        if not clean_messages:
            return

        try:
            # Step 1: 提取跨多条消息复现的表达，避免把主题关键词或跨消息二元组当作口头禅。
            favorite_expressions = self._extract_favorite_expressions(clean_messages)
            all_text = "\n".join(clean_messages)

            # Step 2: 计算平均消息长度
            message_lengths = [len(message) for message in clean_messages]
            avg_len = sum(message_lengths) / len(message_lengths)
            median_len = median(message_lengths)

            # Step 3: 检测表情使用模式
            emojis_by_message = [self._extract_emojis(message) for message in clean_messages]
            emoji_list = [emoji for message_emojis in emojis_by_message for emoji in message_emojis]
            emoji_preferences = [emoji for emoji, _ in Counter(emoji_list).most_common(5)]
            emoji_message_ratio = sum(bool(items) for items in emojis_by_message) / len(clean_messages)

            # Step 4: 推断表达风格
            question_message_ratio = sum(bool(re.search(r"[?？]", message)) for message in clean_messages) / len(
                clean_messages
            )

            style = self._infer_expression_style(
                avg_len=avg_len,
                emoji_ratio=emoji_message_ratio,
                question_ratio=question_message_ratio,
                msg_count=len(clean_messages),
                text=all_text,
            )

            # Step 5: 通过 ProfileStore 持久化
            from src.memory.user_profile import PersonIdentity

            profile = (
                self._profile_store.get_or_create_profile(subject)
                if isinstance(subject, PersonIdentity)
                else self._profile_store.get_profile(subject)
            )
            if profile is None:
                logger.debug(f"用户 {subject} 尚无画像，跳过表达学习")
                return

            patterns = {
                "analysis_version": _EXPRESSION_ANALYSIS_VERSION,
                "favorite_expressions": favorite_expressions,
                "average_message_length": round(avg_len, 1),
                "median_message_length": round(median_len, 1),
                "emoji_preferences": emoji_preferences,
                "emoji_message_ratio": round(emoji_message_ratio, 4),
                "question_message_ratio": round(question_message_ratio, 4),
                "analyzed_message_count": len(clean_messages),
                "updated_at": time.time(),
            }
            profile.expression_style = style
            profile.expression_patterns = patterns
            # 保留旧存储形状，供旧版虚拟 Store 和历史记录迁移。
            if isinstance(getattr(profile, "stats", None), dict):
                profile.stats["_expression_style"] = style
                profile.stats["_expression_patterns"] = patterns

            self._profile_store.save_profile(profile)

            logger.debug(
                "表达画像已更新",
                profile_id=getattr(profile, "profile_id", profile.user_id),
                style=style,
                expressions=len(favorite_expressions),
            )

        except Exception as e:
            logger.warning(f"更新表达画像失败 ({subject}): {e}")

    def get_expression_context(self, user_id: str, max_chars: int = 200, platform: str | None = None) -> str:
        """获取表达画像的 LLM 上下文文本

        Args:
            user_id: 用户 ID
            max_chars: 最大字符数

        Returns:
            格式化文本，最大 max_chars 字符
        """
        profile = (
            self._profile_store.get_profile(user_id, platform=platform)
            if platform
            else self._profile_store.get_profile(user_id)
        )
        if profile is None:
            return ""
        if (
            getattr(profile, "person_type", "person") != "person"
            or getattr(profile, "verification_status", "verified") != "verified"
        ):
            return ""

        stats = getattr(profile, "stats", {})
        if not isinstance(stats, dict):
            stats = {}
        patterns = getattr(profile, "expression_patterns", None) or stats.get("_expression_patterns", {})
        if not isinstance(patterns, dict):
            patterns = {}
        style = getattr(profile, "expression_style", None) or stats.get("_expression_style", "")

        if not patterns and not style:
            return ""

        parts = []
        if style:
            parts.append(f"表达风格: {style}")

        fav = [str(item) for item in patterns.get("favorite_expressions", []) if str(item).strip()]
        if fav:
            parts.append(f"常用表达: {'、'.join(fav[:4])}")

        emoji = [str(item) for item in patterns.get("emoji_preferences", []) if str(item).strip()]
        if emoji:
            parts.append(f"常用表情: {' '.join(emoji[:3])}")

        avg_len = patterns.get("average_message_length", patterns.get("avg_message_length", 0))
        if isinstance(avg_len, (int, float)) and avg_len:
            parts.append(f"平均消息长度: {avg_len:.0f}字")

        result = "【表达特征】" + " | ".join(parts)

        if len(result) > max_chars:
            result = result[: max_chars - 3] + "..."

        return result

    def detect_jargon(self, text: str, user_jargons: list[str]) -> list[str]:
        """检测文本中是否包含已知术语

        Args:
            text: 待检文本
            user_jargons: 已知术语列表

        Returns:
            匹配到的术语列表（按文本出现顺序）
        """
        if not text or not user_jargons:
            return []
        matched: list[str] = []
        text_lower = text.lower()
        for term in user_jargons:
            if term.lower() in text_lower:
                matched.append(term)
        return matched

    # ── 内部方法 ─────────────────────────────────────────────────

    @staticmethod
    def _normalize_messages(messages: list[str]) -> list[str]:
        return [
            re.sub(r"\s+", " ", message.strip()) for message in messages if isinstance(message, str) and message.strip()
        ]

    @classmethod
    def _collect_sample_messages(cls, subject, messages: list[str]) -> list[str]:
        """优先使用平台隔离的最近归档，避免画像随单次小批次剧烈波动。"""
        current_messages = cls._normalize_messages(messages)

        try:
            from src.memory.schema import RawMessageArchive
            from src.memory.user_profile import PersonIdentity

            if not isinstance(subject, PersonIdentity):
                return current_messages[-_MAX_ANALYZED_MESSAGES:]

            rows = list(
                RawMessageArchive.select(RawMessageArchive.content)
                .where(
                    RawMessageArchive.user_id == subject.user_id,
                    RawMessageArchive.platform == subject.platform,
                )
                .order_by(RawMessageArchive.timestamp.desc(), RawMessageArchive.id.desc())
                .limit(_MAX_ANALYZED_MESSAGES)
            )
            archived_messages = cls._normalize_messages([row.content for row in reversed(rows)])
            if not archived_messages:
                return current_messages[-_MAX_ANALYZED_MESSAGES:]

            current_count = len(current_messages)
            current_is_archived = current_count > 0 and archived_messages[-current_count:] == current_messages
            if current_messages and not current_is_archived:
                archived_messages.extend(current_messages)
            return archived_messages[-_MAX_ANALYZED_MESSAGES:]
        except Exception as e:
            logger.debug("读取表达画像历史样本失败，回退当前批次", error=str(e))
            return current_messages[-_MAX_ANALYZED_MESSAGES:]

    @staticmethod
    def _extract_favorite_expressions(messages: list[str]) -> list[str]:
        """提取在多个独立消息中复现的短语，宁缺毋滥。"""
        if len(messages) < 2:
            return []

        support: Counter[str] = Counter()
        whole_segment_support: Counter[str] = Counter()
        first_seen: dict[str, int] = {}

        for message_index, message in enumerate(messages):
            seen_in_message: set[str] = set()
            whole_in_message: set[str] = set()
            text_without_emoji = _EMOJI_RE.sub(" ", message)

            for segment in _CLAUSE_SPLIT_RE.split(text_without_emoji):
                segment = segment.strip()
                if not segment:
                    continue

                normalized_segment = segment.casefold()
                compact_segment = normalized_segment.replace(" ", "")
                if 2 <= len(compact_segment) <= 24 and not compact_segment.isdigit():
                    seen_in_message.add(normalized_segment)
                    whole_in_message.add(normalized_segment)

                for run in _CJK_RUN_RE.findall(segment):
                    max_length = min(len(run), 6)
                    for length in range(2, max_length + 1):
                        for start in range(len(run) - length + 1):
                            seen_in_message.add(run[start : start + length])

                for token in _LATIN_TOKEN_RE.findall(segment):
                    normalized_token = token.casefold()
                    if 2 <= len(normalized_token) <= 24 and not normalized_token.isdigit():
                        seen_in_message.add(normalized_token)
                        whole_in_message.add(normalized_token)

            for candidate in seen_in_message:
                if candidate in _EXPRESSION_STOPWORDS:
                    continue
                support[candidate] += 1
                first_seen.setdefault(candidate, message_index)
            whole_segment_support.update(
                candidate for candidate in whole_in_message if candidate not in _EXPRESSION_STOPWORDS
            )

        message_count = len(messages)
        minimum_support = max(2, math.ceil(message_count * 0.05))
        short_fragment_support = max(3, math.ceil(message_count * 0.10))
        candidates = []
        for candidate, count in support.items():
            compact_length = len(candidate.replace(" ", ""))
            if count < minimum_support or compact_length < 2:
                continue
            if (
                compact_length == 2
                and whole_segment_support[candidate] < minimum_support
                and count < short_fragment_support
            ):
                continue
            candidates.append(candidate)

        candidates.sort(
            key=lambda candidate: (
                -support[candidate],
                -whole_segment_support[candidate],
                -len(candidate.replace(" ", "")),
                first_seen[candidate],
                candidate,
            )
        )

        selected: list[str] = []
        for candidate in candidates:
            if any(candidate in existing or existing in candidate for existing in selected):
                continue
            selected.append(candidate)
            if len(selected) >= _MAX_FAVORITE_EXPRESSIONS:
                break
        return selected

    @staticmethod
    def _extract_emojis(text: str) -> list[str]:
        """从文本中提取所有表情符号

        Args:
            text: 输入文本

        Returns:
            表情符号列表
        """
        return _EMOJI_RE.findall(text)

    @staticmethod
    def _infer_expression_style(
        avg_len: float,
        emoji_ratio: float,
        question_ratio: float,
        msg_count: int,
        text: str,
    ) -> str:
        """根据消息特征推断表达风格

        Args:
            avg_len: 平均消息长度
            emoji_ratio: 包含表情的消息占比
            question_ratio: 包含问号的消息占比
            msg_count: 消息数量
            text: 全部文本

        Returns:
            风格标签
        """
        if msg_count < _MIN_STYLE_MESSAGES:
            return ""

        # 所有标签都描述可直接观察的形式特征，不推断态度或人格。
        formal_count = sum(1 for m in _FORMAL_MARKERS if m in text)
        labels: list[str] = []
        if formal_count >= 2 and avg_len >= 40:
            labels.append("偏正式")
        if avg_len < 15:
            labels.append("短句为主")
        elif avg_len >= 60:
            labels.append("长句较多")
        if emoji_ratio >= 0.30:
            labels.append("常用表情")
        if question_ratio >= 0.35:
            labels.append("常用问句")
        return "、".join(labels) or "日常"
