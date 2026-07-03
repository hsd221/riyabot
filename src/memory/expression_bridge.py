"""表达学习桥接 — 关联 bw_learner 与用户画像

纯启发式规则，不涉及 LLM 调用。通过分析用户的消息文本，
提取表达风格、高频短语、表情偏好和术语，写入用户画像。

使用方式:
    from src.memory.expression_bridge import ExpressionBridge, ExpressionProfile

    bridge = ExpressionBridge(profile_store)
    bridge.update_expression_profile("user_123", messages)
    context = bridge.get_expression_context("user_123")
"""

import re
import time
from dataclasses import dataclass, field

from src.common.logger import get_logger

logger = get_logger("memory.expression")

# ---------------------------------------------------------------------------
# 表情符号检测 — 覆盖常见 Unicode 表情区段
# ---------------------------------------------------------------------------
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # Emoticons
    "\U0001f300-\U0001f5ff"  # Misc Symbols and Pictographs
    "\U0001f680-\U0001f6ff"  # Transport and Map
    "\U0001f1e0-\U0001f1ff"  # Regional Indicator Symbols
    "\U00002600-\U000027bf"  # Misc Symbols + Dingbats
    "\U0001f900-\U0001f9ff"  # Supplemental Symbols
    "\U0001fa00-\U0001fa6f"  # Chess Symbols
    "\U0001fa70-\U0001faff"  # Symbols Extended-A
    "\U0000fe00-\U0000fe0f"  # Variation Selectors
    "\U0000200d"  # Zero Width Joiner
    "]+"
)

# ---------------------------------------------------------------------------
# 表达风格分类阈值
# ---------------------------------------------------------------------------
_STYLE_THRESHOLDS = {
    "活泼": {"emoji_ratio": 0.15, "avg_len_upper": 30},
    "严谨": {"avg_len_lower": 60, "formal_markers": 3},
    "阴阳怪气": {"question_ratio": 0.20},
    "话痨": {"msg_count": 50},
    "简洁": {"avg_len_upper": 15},
}

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
        favorite_expressions: 高频 2-gram/3-gram 短语
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

    def update_expression_profile(self, user_id: str, messages: list[str]) -> None:
        """分析用户最近消息，更新表达画像

        fire-and-forget 调用，异常仅记日志不抛出。

        Args:
            user_id: 用户 ID
            messages: 最近消息文本列表
        """
        if not messages:
            return

        try:
            # Step 1: 提取高频 2-gram 短语
            from src.memory.layer1_summarizer import extract_keywords

            all_text = " ".join(messages)
            favorite_expressions = extract_keywords(all_text, max_keywords=8)

            # Step 2: 计算平均消息长度
            avg_len = sum(len(m) for m in messages) / len(messages)

            # Step 3: 检测表情使用模式
            emoji_list = self._extract_emojis(all_text)
            emoji_count = len(emoji_list)
            emoji_ratio = emoji_count / max(len(all_text), 1)

            # Step 4: 推断表达风格
            question_count = all_text.count("？") + all_text.count("?")
            question_ratio = question_count / max(len(messages), 1)

            style = self._infer_expression_style(
                avg_len=avg_len,
                emoji_ratio=emoji_ratio,
                question_ratio=question_ratio,
                msg_count=len(messages),
                text=all_text,
            )

            # Step 5: 通过 ProfileStore 持久化
            profile = self._profile_store.get_profile(user_id)
            if profile is None:
                logger.debug(f"用户 {user_id} 尚无画像，跳过表达学习")
                return

            # 存储到 stats 字典（使用 _ 前缀避免与业务 key 冲突）
            profile.stats["_expression_style"] = style
            profile.stats["_expression_patterns"] = {
                "favorite_expressions": favorite_expressions,
                "avg_message_length": round(avg_len, 1),
                "emoji_preferences": list(set(emoji_list))[:5],
                "emoji_ratio": round(emoji_ratio, 4),
                "question_ratio": round(question_ratio, 4),
                "analyzed_message_count": len(messages),
                "updated_at": time.time(),
            }

            self._profile_store.save_profile(profile)

            logger.debug(
                "表达画像已更新",
                user_id=user_id,
                style=style,
                expressions=len(favorite_expressions),
            )

        except Exception as e:
            logger.warning(f"更新表达画像失败 ({user_id}): {e}")

    def get_expression_context(self, user_id: str, max_chars: int = 200) -> str:
        """获取表达画像的 LLM 上下文文本

        Args:
            user_id: 用户 ID
            max_chars: 最大字符数

        Returns:
            格式化文本，最大 max_chars 字符
        """
        profile = self._profile_store.get_profile(user_id)
        if profile is None:
            return ""

        patterns = profile.stats.get("_expression_patterns", {})
        style = profile.stats.get("_expression_style", "")

        if not patterns and not style:
            return ""

        parts = []
        if style:
            parts.append(f"表达风格: {style}")

        fav = patterns.get("favorite_expressions", [])
        if fav:
            parts.append(f"高频词: {'、'.join(fav[:4])}")

        emoji = patterns.get("emoji_preferences", [])
        if emoji:
            parts.append(f"常用表情: {' '.join(emoji[:3])}")

        avg_len = patterns.get("avg_message_length", 0)
        if avg_len:
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
            emoji_ratio: 表情字符占比
            question_ratio: 平均每消息问号数
            msg_count: 消息数量
            text: 全部文本

        Returns:
            风格标签
        """
        # 正式用语检测
        formal_count = sum(1 for m in _FORMAL_MARKERS if m in text)

        # 多条件判断（优先级从高到低）
        if formal_count >= 3 and avg_len > 60:
            return "严谨"
        if emoji_ratio >= 0.15 and avg_len < 30:
            return "活泼"
        if question_ratio >= 0.20:
            return "阴阳怪气"
        if msg_count >= 50:
            return "话痨"
        if avg_len < 15:
            return "简洁"

        # 默认 — 根据平均长度细分
        if avg_len < 30:
            return "简洁"
        return "中性"
