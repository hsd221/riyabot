"""记忆强化追踪与反馈分析

提供 ReinforcementTracker 类，将 reinforce_memory() 函数与 MemoryStore 持久化连接，
实现检索后记忆使用情况的追踪和权重动态调整。

使用方式:
    from src.memory.feedback import ReinforcementTracker
    from src.memory import get_memory_store

    tracker = ReinforcementTracker(get_memory_store())

    # 分析记忆在回复中的使用
    usage = tracker.analyze_reply_for_memory_usage(reply_text, retrieved_atoms)

    # 强化权重
    await tracker.apply_reinforcement(
        [aid for aid, lv in usage.items() if lv != "none"],
        level="normal",
    )
"""

import datetime
import json
import time
from typing import Any

from src.common.logger import get_logger
from src.memory.atom import MemoryAtom, AtomType, DecayType, reinforce_memory
from src.memory.store import MemoryStore

logger = get_logger("memory.feedback")

_FLOAT_EPS = 1e-9  # 浮点比较容差


# ── 相似度工具 ──────────────────────────────────────────────────


def _char_bigram_jaccard(text1: str, text2: str) -> float:
    """计算两个文本的字符 2-gram Jaccard 相似度

    将每个文本拆分为连续的 2 字符片段（character bigram），
    计算交集与并集的大小之比。

    Args:
        text1: 第一个文本
        text2: 第二个文本

    Returns:
        0.0 ~ 1.0 的相似度分数
    """
    if not text1 or not text2:
        return 0.0
    bigrams1 = {text1[i : i + 2] for i in range(len(text1) - 1)}
    bigrams2 = {text2[i : i + 2] for i in range(len(text2) - 1)}
    if not bigrams1 or not bigrams2:
        return 0.0
    intersection = bigrams1 & bigrams2
    union = bigrams1 | bigrams2
    return len(intersection) / len(union)


# ── 主类 ────────────────────────────────────────────────────────


class ReinforcementTracker:
    """记忆强化追踪器

    分析记忆在 LLM 回复中的实际使用情况，根据使用程度应用不同强度的反馈，
    并通过 MemoryStore 持久化权重调整。

    职责边界:
        - 仅处理算法层面的记忆使用度分析和权重调整
        - 不涉及 LLM 调用（由调用方决定何时触发）
        - 不导入任何 chat 模块（避免循环依赖）
    """

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

    # ── 分析 ────────────────────────────────────────────────────

    def analyze_reply_for_memory_usage(
        self,
        reply_text: str,
        atoms: list[MemoryAtom],
    ) -> dict[str, str]:
        """分析回复中对各记忆原子的使用程度

        通过字符 2-gram Jaccard 相似度计算每个记忆内容与回复文本的重叠程度，
        返回每个 atom_id 对应的强化等级建议。

        判定阈值:
            strong  (> 0.6): 记忆内容与回复高度重叠 → 重点提及
            normal  [0.3, 0.6]: 中等程度重叠 → 用到但非重点
            none    (< 0.3):  低重叠 → 几乎未使用

        Args:
            reply_text: 生成的回复文本
            atoms: 检索到的记忆原子列表（MemoryAtom dataclass）

        Returns:
            {atom_id: "none" | "normal" | "strong"} 映射
        """
        if not reply_text or not atoms:
            return {}

        result: dict[str, str] = {}
        for atom in atoms:
            if not atom.content:
                result[atom.atom_id] = "none"
                continue
            similarity = _char_bigram_jaccard(reply_text, atom.content)
            if similarity > 0.6:
                result[atom.atom_id] = "strong"
            elif similarity >= 0.3:
                result[atom.atom_id] = "normal"
            else:
                result[atom.atom_id] = "none"

        logger.debug(
            "Memory usage analysis: %d atoms analyzed, strong=%d, normal=%d, none=%d",
            len(atoms),
            sum(1 for v in result.values() if v == "strong"),
            sum(1 for v in result.values() if v == "normal"),
            sum(1 for v in result.values() if v == "none"),
        )
        return result

    # ── 强化执行 ────────────────────────────────────────────────

    async def apply_reinforcement(
        self,
        atom_ids: list[str],
        level: str = "normal",
    ) -> None:
        """批量加载记忆原子 → 内存中强化 → 单事务写入

        使用 get_atoms_batch() + update_atoms_batch() 将 N*2 次 SQL 优化为 2 次数据库交互。

        Args:
            atom_ids: 要强化的原子 ID 列表
            level: 强化等级（"none" / "normal" / "strong"）

        Logs:
            info 汇总（atom_count, updated, not_found, duration_ms）
            warning 未找到的原子数
        """
        if not atom_ids:
            return

        t0 = time.time()

        atoms_data = await self.store.get_atoms_batch(atom_ids)

        not_found = len(atom_ids) - len(atoms_data)
        if not_found:
            logger.warning(
                "强化跳过 %d/%d 个记忆原子（不存在）",
                not_found,
                len(atom_ids),
            )

        if not atoms_data:
            return

        updates_list: list[tuple[str, dict[str, Any]]] = []
        for atom_id, data in atoms_data.items():
            atom_dc = self._dict_to_atom(data)
            updated = reinforce_memory(atom_dc, level)
            updates = self._build_updates(atom_dc, updated)
            if updates:
                updates_list.append((atom_id, updates))

        if updates_list:
            await self.store.update_atoms_batch(updates_list)

            # 同步到 Qdrant：更新每个原子的 payload 字段
            for atom_id, updates in updates_list:
                try:
                    qdrant_updates = {}
                    for key in ("weight", "reinforcement_count", "last_reinforced_at", "last_accessed_at"):
                        if key in updates:
                            val = updates[key]
                            # datetime 对象转为 ISO 字符串（Qdrant payload 需 JSON 可序列化）
                            if hasattr(val, "isoformat"):
                                val = val.isoformat()
                            qdrant_updates[key] = val
                    if qdrant_updates:
                        await self.store.qdrant.set_atom_payload(atom_id, qdrant_updates)
                except Exception as e:
                    logger.warning("Qdrant 同步失败 (reinforcement): %s", e)

        duration_ms = (time.time() - t0) * 1000
        logger.info(
            "强化反馈完成: atom_count=%d, updated=%d, not_found=%d, duration_ms=%.1f",
            len(atom_ids),
            len(updates_list),
            not_found,
            duration_ms,
        )

    async def apply_reinforcement_async(
        self,
        atom_ids: list[str],
        level: str = "normal",
    ) -> None:
        """异步强化 — 专为聊天事件循环中的调用方封装

        行为与 apply_reinforcement 完全一致，显式标记 async
        以便调用方明确感知异步 I/O 的发生。
        """
        await self.apply_reinforcement(atom_ids, level)

    # ── 内部工具 ────────────────────────────────────────────────

    @staticmethod
    def _to_timestamp(value: Any) -> float:
        """将多种时间表示统一转为 Unix 时间戳（float）

        兼容 Peewee DateTimeField（返回 datetime）、
        ISO 格式字符串、以及原始 float/int。
        """
        if value is None:
            return time.time()
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, datetime.datetime):
            return value.timestamp()
        if isinstance(value, str):
            try:
                return datetime.datetime.fromisoformat(value).timestamp()
            except (ValueError, TypeError):
                return time.time()
        return time.time()

    @classmethod
    def _dict_to_atom(cls, data: dict[str, Any]) -> MemoryAtom:
        """将 store.get_atom() 返回的 dict 转为 MemoryAtom dataclass

        该转换是必要的，因为 store 返回的是 Peewee 模型序列化后的字典，
        而 reinforce_memory() 等函数操作的是 atom.py 中的纯 dataclass。

        Args:
            data: 来自 store.get_atom() 的字典

        Returns:
            可用于 reinforce_memory() / compute_weight() 的 dataclass
        """
        entities = data.get("entities", [])
        if isinstance(entities, str):
            try:
                entities = json.loads(entities)
            except (json.JSONDecodeError, TypeError):
                entities = []
        if not isinstance(entities, list):
            entities = []

        return MemoryAtom(
            atom_id=data["atom_id"],
            atom_type=AtomType(data.get("atom_type", "factual")),
            content=data.get("content", ""),
            entities=entities,
            importance=float(data.get("importance", 0.5)),
            confidence=float(data.get("confidence", 0.5)),
            weight=float(data.get("weight", 0.5)),
            created_at=cls._to_timestamp(data.get("created_at")),
            last_accessed_at=cls._to_timestamp(data.get("last_accessed_at")),
            last_reinforced_at=(
                cls._to_timestamp(data["last_reinforced_at"]) if data.get("last_reinforced_at") is not None else None
            ),
            ttl_days=float(data.get("ttl_days", 7)),
            decay_type=DecayType(data.get("decay_type", "exponential")),
            reinforcement_count=int(data.get("reinforcement_count", 0)),
            source_scene=str(data.get("source_scene", "chat")),
            privacy_level=str(data.get("privacy_level", "public")),
            trace_chain_id=data.get("trace_chain_id"),
            status=str(data.get("status", "active")),
        )

    @staticmethod
    def _build_updates(
        old_dc: MemoryAtom,
        new_dc: MemoryAtom,
    ) -> dict[str, Any]:
        """构建 store.update_atom() 可接受的更新字典

        只包含实际发生变化的字段，datetime 字段转为
        datetime.datetime 对象供 Peewee ORM 使用。

        Args:
            old_dc: 原始 MemoryAtom dataclass（来自 store）
            new_dc: reinforce_memory() 返回的更新后 dataclass

        Returns:
            可直接传入 store.update_atom() 的更新字典
        """
        updates: dict[str, Any] = {}

        if abs(new_dc.weight - old_dc.weight) > _FLOAT_EPS:
            updates["weight"] = new_dc.weight

        if new_dc.reinforcement_count != old_dc.reinforcement_count:
            updates["reinforcement_count"] = new_dc.reinforcement_count

        if new_dc.last_reinforced_at != old_dc.last_reinforced_at:
            updates["last_reinforced_at"] = (
                datetime.datetime.fromtimestamp(new_dc.last_reinforced_at)
                if new_dc.last_reinforced_at is not None
                else None
            )

        if abs(new_dc.last_accessed_at - old_dc.last_accessed_at) > 1e-6:
            updates["last_accessed_at"] = datetime.datetime.fromtimestamp(new_dc.last_accessed_at)

        return updates
