"""第3层：写入与检索引擎 — 双层存储写入 + 向量/关键词检索

第3层是记忆系统的读写操作枢纽，对上为记忆处理流水线提供统一写入和检索接口，
对下调用 MemoryStore（SQLite + Qdrant）完成具体存储。

Classes:
    PartitionManager:   场景分区管理器
    MemoryWriter:       第3层写入器
    MemoryRetriever:    第3层检索器
    RetrievedAtom:      检索结果封装 dataclass

Functions:
    cosine_similarity:  计算余弦相似度
    rank_atoms:         综合排序（权重 × 相似度）
"""

from __future__ import annotations

import json
import math
import datetime as _dt
import hashlib
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Optional

from src.common.logger import get_logger
from src.memory.atom import (
    MemoryAtom as MemoryAtomDC,
    EpisodicDetail,
    SemanticDetail,
    AtomType,
    DecayType,
    get_fade_level,
    update_weight,
    to_datetime,
    to_timestamp,
)
from src.memory.graph_store import GraphStore
from src.memory.store import MemoryStore
from src.memory.schema import (
    memory_db,
    EpisodicDetail as EpisodicDetailModel,
    SemanticDetail as SemanticDetailModel,
    MemoryAtom as MemoryAtomModel,
)
from src.memory.types import AtomDict
from src.memory.write_ops import WriteOpLogger, OpType, WriteOperation
from src.memory.embedding_utils import generate_embedding, generate_query_embedding

logger = get_logger("memory.layer3")

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算余弦相似度

    如果向量为空或零向量，返回 0.0。

    Args:
        a: 向量 A
        b: 向量 B

    Returns:
        余弦相似度（范围 0.0-1.0）
    """
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def rank_atoms(atoms: list[AtomDict], query_embedding: Optional[list[float]] = None) -> list[AtomDict]:
    """基于权重 + 可选相似度进行综合排序

    当提供 query_embedding 时，final_score = weight × cosine_similarity；
    否则 final_score = weight。

    Args:
        atoms: 原子字典列表（需包含 "weight" 字段，可选 "embedding"）
        query_embedding: 查询向量（可选）

    Returns:
        按 final_score 降序排列的原子列表，每项新增 "final_score" 字段
    """
    for atom in atoms:
        weight = atom.get("weight", 0.0)
        if query_embedding:
            atom_emb = atom.get("embedding")
            similarity = cosine_similarity(query_embedding, atom_emb) if atom_emb else 0.0
        else:
            similarity = 1.0
        atom["final_score"] = weight * similarity
    return sorted(atoms, key=lambda a: a["final_score"], reverse=True)


def _convert_decay_type(val: Any) -> str:
    """将 DecayType enum 或字符串转为统一字符串形式"""
    if isinstance(val, DecayType):
        return val.value
    return str(val)


def _convert_atom_type(val: Any) -> str:
    """将 AtomType enum 或字符串转为统一字符串形式"""
    if isinstance(val, AtomType):
        return val.value
    return str(val)


def _entities_include_user(entities: Any, user_id: str) -> bool:
    """精确判断 entities 中是否包含目标 user_id。"""
    if not user_id or entities is None:
        return False

    if isinstance(entities, str):
        try:
            return _entities_include_user(json.loads(entities), user_id)
        except (json.JSONDecodeError, TypeError):
            return entities == user_id

    if isinstance(entities, dict):
        for key in ("user_id", "id", "uid", "qq"):
            value = entities.get(key)
            if value is not None and str(value) == user_id:
                return True
        return False

    if isinstance(entities, (list, tuple, set)):
        return any(_entities_include_user(item, user_id) for item in entities)

    return str(entities) == user_id


# ---------------------------------------------------------------------------
# 分区管理器
# ---------------------------------------------------------------------------


class PartitionManager:
    """分区管理器 — 按 source_scene 分区存储

    提供场景分区定义、查询过滤条件构建、分区统计等功能。
    分区策略使群聊、私聊、梦境等不同来源的记忆在检索时可以隔离。
    """

    PARTITIONS: dict[str, str] = {
        "group_chat": "群聊记忆",
        "private_chat": "私聊记忆",
        "dream": "梦境记忆",
        "system": "系统记忆",
    }

    @classmethod
    def get_partition(cls, source_scene: str) -> str:
        """获取分区的中文描述

        Args:
            source_scene: 来源场景标识

        Returns:
            分区中文名，未知场景返回 "unknown"
        """
        return cls.PARTITIONS.get(source_scene, "unknown")

    @classmethod
    def get_partition_filters(cls, source_scene: str) -> dict[str, str]:
        """获取分区对应的过滤条件

        Args:
            source_scene: 来源场景标识（如 group_chat, private_chat）

        Returns:
            可直接用于 Qdrant 过滤或 SQLite 查询的条件字典
        """
        return {"source_scene": source_scene}

    @classmethod
    async def get_partition_stats(cls, store: MemoryStore) -> dict[str, int]:
        """获取各分区的记忆数量统计

        Args:
            store: MemoryStore 实例

        Returns:
            {分区场景: 记忆数量} 字典
        """
        stats: dict[str, int] = {}
        for scene in cls.PARTITIONS:
            try:
                with memory_db:
                    count = MemoryAtomModel.select().where(MemoryAtomModel.source_scene == scene).count()
                stats[scene] = count
            except Exception:
                stats[scene] = 0
        return stats


# ---------------------------------------------------------------------------
# 隐私级别常量
# ---------------------------------------------------------------------------

PRIVACY_PUBLIC = "public"
PRIVACY_CONTEXT_SENSITIVE = "context_sensitive"
PRIVACY_PRIVATE = "private"


# ---------------------------------------------------------------------------
# 跨场景隐私过滤器
# ---------------------------------------------------------------------------


class PrivacyFilter:
    """跨场景隐私过滤器 — 三级隐私模型

    在跨场景记忆流通时根据隐私级别过滤记忆原子：

    - PUBLIC: 任何场景均可访问
    - CONTEXT_SENSITIVE: 仅在相同场景类型内流通（group→group, private→private）
    - PRIVATE: 仅在私聊中访问（同用户）

    Usage:
        pf = PrivacyFilter()
        safe = pf.filter_atoms(atoms, target_scene="group_chat", target_scope="group_123")
    """

    @staticmethod
    def filter_atoms(
        atoms: list[AtomDict],
        target_scene: str,
        target_scope: str,
    ) -> list[AtomDict]:
        """按隐私级别过滤记忆原子

        Args:
            atoms: 原子字典列表（_model_to_result 格式，需包含 privacy_level 和 source_scene）
            target_scene: 目标场景类型（"group_chat" 或 "private_chat"）
            target_scope: 目标范围标识（group_id 或 user_id）

        Returns:
            过滤后的原子字典列表
        """
        total = len(atoms)
        filtered: list[AtomDict] = []
        for atom in atoms:
            if PrivacyFilter._can_access(atom, target_scene, target_scope):
                filtered.append(atom)

        removed = total - len(filtered)
        if removed > 0:
            logger.debug(
                "隐私过滤: 移除 %d/%d 条记忆",
                removed,
                total,
            )
            logger.debug(
                "隐私过滤详情",
                target_scene=target_scene,
                removed=removed,
                total=total,
            )
        return filtered

    @staticmethod
    def _can_access(atom: AtomDict, target_scene: str, target_scope: str) -> bool:
        """判断记忆原子在目标场景中是否可访问

        Args:
            atom: 原子字典（含 privacy_level, source_scene 字段）
            target_scene: 目标场景
            target_scope: 目标范围

        Returns:
            True 表示可访问
        """
        privacy = atom.get("privacy_level", PRIVACY_CONTEXT_SENSITIVE)
        atom_scene = atom.get("source_scene", "unknown")
        atom_scope = atom.get("source_id")

        if privacy == PRIVACY_PUBLIC:
            return True

        if privacy == PRIVACY_PRIVATE:
            # PRIVATE: 仅在同一私聊中可访问；历史数据缺少 source_id 时只允许私聊场景兜底。
            return target_scene == "private_chat" and (not atom_scope or atom_scope == target_scope)

        if privacy == PRIVACY_CONTEXT_SENSITIVE:
            if target_scene != atom_scene:
                return False
            # 私聊的上下文敏感记忆只在同一 stream 内复用；历史数据缺少 source_id 时保守放行同私聊场景。
            if target_scene == "private_chat":
                return not atom_scope or atom_scope == target_scope
            return True

        return False


# ---------------------------------------------------------------------------
# 检索结果封装
# ---------------------------------------------------------------------------


@dataclass
class RetrievedAtom:
    """检索结果封装

    一条检索到的记忆原子及其评分信息，用于返回给调用方。

    Attributes:
        atom_id: 原子唯一 ID
        content: 原子内容
        atom_type: 原子类型字符串
        weight: 原子权重
        similarity_score: 向量相似度分数
        final_score: 综合评分（weight × similarity）
        fade_level: 褪色等级（完整/摘要/模糊/残影）
        source_scene: 来源场景
        source_id: 来源聊天流 ID
        importance: 重要性
        confidence: 置信度
        created_at: 创建时间戳
        metadata: 额外元数据
    """

    atom_id: str
    content: str
    atom_type: str
    weight: float
    similarity_score: float = 0.0
    final_score: float = 0.0
    fade_level: str = "残影"
    source_scene: str = "unknown"
    source_id: Optional[str] = None
    importance: float = 0.5
    confidence: float = 0.5
    created_at: Optional[float] = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _resolve_scene_type(stream_id: str, scene_type: Optional[str] = None) -> str:
    """解析聊天场景类型。

    优先使用调用方从 ChatStream 得到的明确类型；仅在旧调用未传入时保留兼容推断。
    """
    if scene_type in ("group_chat", "private_chat", "dream", "system"):
        return scene_type
    return "group_chat" if "group" in str(stream_id) else "private_chat"


def _global_memory_enabled() -> bool:
    """读取全局记忆开关，配置不可用时默认关闭。"""
    try:
        from src.config.config import global_config

        return bool(getattr(global_config.memory, "global_memory", False))
    except Exception:
        return False


def _stream_id_from_blacklist_entry(entry: str) -> Optional[str]:
    """将 global_memory_blacklist 条目转换为 ChatStream.stream_id。"""
    parts = [part.strip() for part in str(entry).split(":")]
    if len(parts) != 3 or not parts[0] or not parts[1] or not parts[2]:
        return None

    platform, chat_id, chat_type = parts
    if chat_type in ("group", "group_chat"):
        key = f"{platform}_{chat_id}"
    elif chat_type in ("private", "private_chat"):
        key = f"{platform}_{chat_id}_private"
    else:
        return None
    return hashlib.md5(key.encode()).hexdigest()


def _global_memory_blacklist_source_ids() -> set[str]:
    """读取全局记忆黑名单并转换为 source_id 集合。"""
    try:
        from src.config.config import global_config

        entries = getattr(global_config.memory, "global_memory_blacklist", []) or []
    except Exception:
        return set()

    source_ids: set[str] = set()
    for entry in entries:
        source_id = _stream_id_from_blacklist_entry(str(entry))
        if source_id:
            source_ids.add(source_id)
        else:
            logger.warning("忽略无效的全局记忆黑名单条目: %s", entry)
    return source_ids


def _global_memory_allowed(stream_id: str, include_global: Optional[bool] = None) -> bool:
    """判断当前 stream 是否允许进行全局记忆检索。"""
    enabled = _global_memory_enabled() if include_global is None else include_global
    if not enabled:
        return False
    return stream_id not in _global_memory_blacklist_source_ids()


# ---------------------------------------------------------------------------
# 写入器
# ---------------------------------------------------------------------------


class MemoryWriter:
    """第3层写入器 — 将记忆原子写入双层存储（SQLite + Qdrant）

    职责链：接收 MemoryAtom dataclass → 校验 → 计算权重 →
    SQLite 写入（含扩展详情）→ Qdrant 同步 → 写操作日志记录。

    使用方式:
        writer = MemoryWriter(store, op_logger)
        atom_id = await writer.write_atom(
            atom=my_atom,
            episodic_detail=detail,
        )
    """

    VALID_SCENES = {"group_chat", "private_chat", "dream", "system", "unknown"}

    def __init__(
        self,
        store: MemoryStore,
        op_logger: Optional[WriteOpLogger] = None,
    ):
        """初始化写入器

        Args:
            store: MemoryStore 实例（承载 SQLite + Qdrant）
            op_logger: WriteOpLogger 实例，不传则不记录写操作日志
        """
        self.store = store
        self.op_logger = op_logger

    # ── 核心写入方法 ───────────────────────────────────────

    async def write_atom(
        self,
        atom: MemoryAtomDC,
        episodic_detail: Optional[EpisodicDetail] = None,
        semantic_detail: Optional[SemanticDetail] = None,
    ) -> str:
        """写一个记忆原子（含扩展详情）

        工作流程:
            1. 校验原子字段完整性
            2. 计算初始权重
            3. 写入 SQLite（MemoryAtom + 扩展详情表）
            4. 如果有 embedding，同步写入 Qdrant
            5. 记录写操作日志

        Args:
            atom: 记忆原子 dataclass
            episodic_detail: 情景记忆扩展（可选，仅 episodic 类型）
            semantic_detail: 语义记忆扩展（可选，仅 factual/preference 类型）

        Returns:
            写入的 atom_id

        Raises:
            ValueError: 原子校验失败
        """
        if not self._validate_atom(atom):
            raise ValueError(f"记忆原子校验失败: {atom.atom_id}")

        # 1. 计算初始权重（如果当前 weight 为默认值 0.5）
        if atom.weight == 0.5:
            atom = update_weight(atom)

        # 2. 准备 SQLite 字典
        store_dict = self._atom_to_store_dict(atom)

        # 3. 写入 SQLite
        try:
            async with WriteOperation(
                self.op_logger,
                OpType.INSERT_ATOM,
                "sqlite",
                atom_ids=[atom.atom_id],
                payload={"atom": store_dict},
            ):
                await self.store.insert_atom(store_dict)
        except Exception as e:
            logger.error(f"写入记忆原子到 SQLite 失败: {atom.atom_id}, {e}")
            raise

        # 4. 写入扩展详情表
        if episodic_detail is not None:
            await self._write_episodic_detail(atom.atom_id, episodic_detail)
        if semantic_detail is not None:
            await self._write_semantic_detail(atom.atom_id, semantic_detail)

        # 5. 生成 embedding（如果尚未设置）
        if not atom.embedding:
            embedding_vector = await generate_embedding(atom.content)
            if embedding_vector:
                atom.embedding = embedding_vector

        # 6. 同步到 Qdrant（如果有 embedding）
        if atom.embedding:
            try:
                async with WriteOperation(
                    self.op_logger,
                    OpType.INSERT_ATOM,
                    "qdrant",
                    atom_ids=[atom.atom_id],
                ):
                    if not await self._upsert_qdrant(atom):
                        raise RuntimeError("Qdrant upsert 返回 False")
            except Exception as e:
                logger.warning(f"Qdrant 写入失败（已写入 SQLite）: {atom.atom_id}, {e}")

        logger.debug(
            "记忆原子写入完成",
            extra={
                "atom_id": atom.atom_id,
                "atom_type": atom.atom_type.value,
                "scene": atom.source_scene,
                "weight": atom.weight,
            },
        )
        return atom.atom_id

    async def batch_write(self, atoms: list[MemoryAtomDC]) -> list[str]:
        """批量写入记忆原子

        全部在同一个 SQLite 事务中提交。每个原子的 Qdrant 写入各自独立。

        Args:
            atoms: 记忆原子列表

        Returns:
            写入成功的 atom_id 列表
        """
        if not atoms:
            return []

        atom_ids: list[str] = []

        with memory_db.atomic():
            for atom in atoms:
                if not self._validate_atom(atom):
                    logger.warning(f"批量写入跳过校验失败的原子: {atom.atom_id}")
                    continue

                if atom.weight == 0.5:
                    atom = update_weight(atom)

                store_dict = self._atom_to_store_dict(atom)

                try:
                    async with WriteOperation(
                        self.op_logger,
                        OpType.BATCH_INSERT,
                        "sqlite",
                        atom_ids=[atom.atom_id],
                        payload={"atom": store_dict},
                    ):
                        await self.store.insert_atom(store_dict)
                    atom_ids.append(atom.atom_id)

                    # 生成 embedding（如果尚未设置）
                    if not atom.embedding:
                        emb_vec = await generate_embedding(atom.content)
                        if emb_vec:
                            atom.embedding = emb_vec

                    # 独立写入 Qdrant
                    if atom.embedding:
                        try:
                            async with WriteOperation(
                                self.op_logger,
                                OpType.BATCH_INSERT,
                                "qdrant",
                                atom_ids=[atom.atom_id],
                            ):
                                if not await self._upsert_qdrant(atom):
                                    raise RuntimeError("Qdrant upsert 返回 False")
                        except Exception as e:
                            logger.warning(f"批量写入 Qdrant 失败: {atom.atom_id}, {e}")
                except Exception as e:
                    logger.error(f"批量写入原子失败: {atom.atom_id}, {e}")

        logger.info(
            "批量写入完成",
            extra={"total": len(atoms), "succeeded": len(atom_ids)},
        )
        return atom_ids

    async def update_atom(
        self,
        atom_id: str,
        updates: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """更新记忆原子，并在相关字段变更时重新计算权重

        Args:
            atom_id: 原子 ID
            updates: 要更新的字段字典

        Returns:
            更新后的原子字典，原子不存在返回 None
        """
        current = await self.store.get_atom(atom_id)
        if current is None:
            logger.warning(f"更新不存在的记忆原子: {atom_id}")
            return None

        # 合并更新并重新计算 weight
        merged = {**current, **updates}

        # 如果 importance / confidence 变更，重新计算 weight
        weight_keys = {"importance", "confidence"}
        if weight_keys & set(updates.keys()):
            try:
                temp_atom = self._dict_to_atom(merged)
                temp_atom = update_weight(temp_atom)
                merged["weight"] = temp_atom.weight
            except Exception as e:
                logger.warning(f"权重重新计算失败: {e}")

        # 提取需要传递给 store.update_atom 的字段（排除 store 不接受的字段）
        store_updates = {}
        skip_fields = {"embedding", "created_at", "atom_id"}
        for key, value in merged.items():
            if key in skip_fields:
                continue
            if key == "atom_type" and isinstance(value, AtomType):
                value = value.value
            if key == "decay_type" and isinstance(value, DecayType):
                value = value.value
            if key in ("created_at", "last_accessed_at", "last_reinforced_at"):
                if isinstance(value, str):
                    try:
                        _dt.datetime.fromisoformat(value)
                    except (ValueError, TypeError):
                        continue
                value = to_timestamp(value)
            store_updates[key] = value

        try:
            async with WriteOperation(
                self.op_logger,
                OpType.UPDATE_ATOM,
                "sqlite",
                atom_ids=[atom_id],
                payload={"updates": store_updates},
            ):
                success = await self.store.update_atom(atom_id, store_updates)
                if not success:
                    logger.warning(f"更新记忆原子返回 False: {atom_id}")
        except Exception as e:
            logger.error(f"更新记忆原子失败: {atom_id}, {e}")
            return None

        # 同步到 Qdrant
        try:
            if "content" in store_updates:
                # 内容变更：重新生成 embedding 并全量 upsert
                embedding_vector = await generate_embedding(store_updates.get("content") or merged.get("content", ""))
                if embedding_vector:
                    qdrant_payload = {
                        "atom_id": atom_id,
                        "atom_type": _convert_atom_type(merged.get("atom_type", "factual")),
                        "weight": merged.get("weight", 0.5),
                        "importance": merged.get("importance", 0.5),
                        "confidence": merged.get("confidence", 0.5),
                        "status": merged.get("status", "active"),
                        "source_scene": merged.get("source_scene", "chat"),
                        "source_id": merged.get("source_id"),
                        "privacy_level": merged.get("privacy_level", "context_sensitive"),
                    }
                    async with WriteOperation(
                        self.op_logger,
                        OpType.UPDATE_ATOM,
                        "qdrant",
                        atom_ids=[atom_id],
                        payload={"updates": store_updates},
                    ):
                        if not await self.store.qdrant.upsert_atom_vector(
                            point_id=atom_id,
                            vector=embedding_vector,
                            payload=qdrant_payload,
                        ):
                            raise RuntimeError("Qdrant upsert 返回 False")
            else:
                # 非内容字段变更：仅更新 Qdrant payload
                qdrant_updates = {}
                for key in ("weight", "importance", "confidence", "status", "privacy_level", "source_scene", "source_id"):
                    if key in store_updates:
                        qdrant_updates[key] = store_updates[key]
                if qdrant_updates:
                    async with WriteOperation(
                        self.op_logger,
                        OpType.UPDATE_ATOM,
                        "qdrant",
                        atom_ids=[atom_id],
                        payload={"updates": qdrant_updates},
                    ):
                        if not await self.store.qdrant.set_atom_payload(atom_id, qdrant_updates):
                            raise RuntimeError("Qdrant payload 更新返回 False")
        except Exception as e:
            logger.warning(f"Qdrant 同步失败 (update_atom): {atom_id}, {e}")

        return await self.store.get_atom(atom_id)

    # ── 内部方法 ───────────────────────────────────────────

    def _validate_atom(self, atom: MemoryAtomDC) -> bool:
        """校验记忆原子字段完整性

        检查项:
            - atom_id 非空
            - content 非空
            - importance, confidence 在 [0, 1] 范围内
            - atom_type 是有效的 AtomType
            - source_scene 是已知场景

        Args:
            atom: 待校验的记忆原子

        Returns:
            True 表示校验通过
        """
        if not atom.atom_id:
            logger.warning("原子校验失败: atom_id 为空")
            return False
        if not atom.content:
            logger.warning("原子校验失败: content 为空")
            return False
        if not (0.0 <= atom.importance <= 1.0):
            logger.warning(f"原子校验失败: importance 超出范围 [{atom.importance}]")
            return False
        if not (0.0 <= atom.confidence <= 1.0):
            logger.warning(f"原子校验失败: confidence 超出范围 [{atom.confidence}]")
            return False
        if not isinstance(atom.atom_type, AtomType):
            logger.warning(f"原子校验失败: 无效 atom_type [{atom.atom_type}]")
            return False
        if atom.source_scene not in self.VALID_SCENES:
            logger.warning(f"原子校验失败: 未知 source_scene [{atom.source_scene}]")
            return False
        return True

    def _atom_to_store_dict(self, atom: MemoryAtomDC) -> dict[str, Any]:
        """将 MemoryAtom dataclass 转为 store.insert_atom 可接受的字典

        处理字段类型转换: enum→str, 时间→float, 列表→JSON。

        Args:
            atom: 记忆原子 dataclass

        Returns:
            适合 store.insert_atom 的字段字典，同时保持 WriteOperation payload 可 JSON 序列化
        """
        data: dict[str, Any] = {
            "atom_id": atom.atom_id,
            "atom_type": _convert_atom_type(atom.atom_type),
            "content": atom.content,
            "importance": atom.importance,
            "confidence": atom.confidence,
            "weight": atom.weight,
            "created_at": to_timestamp(atom.created_at),
            "last_accessed_at": to_timestamp(atom.last_accessed_at),
            "ttl_days": int(atom.ttl_days),
            "decay_type": _convert_decay_type(atom.decay_type),
            "reinforcement_count": atom.reinforcement_count,
            "source_scene": atom.source_scene,
            "source_id": atom.source_id,
            "privacy_level": atom.privacy_level,
            "status": atom.status,
            "embedding_id": atom.atom_id,
        }

        # entities: 转为 JSON 字符串
        if atom.entities:
            data["entities"] = json.dumps(atom.entities, ensure_ascii=False)

        # trace_chain_id: 非空则传入
        if atom.trace_chain_id:
            data["trace_chain_id"] = atom.trace_chain_id

        # last_reinforced_at: 有值则转换，无值让 store 用默认值
        if atom.last_reinforced_at is not None:
            data["last_reinforced_at"] = to_timestamp(atom.last_reinforced_at)

        return data

    def _dict_to_atom(self, data: dict[str, Any]) -> MemoryAtomDC:
        """将 store 返回的字典转为 MemoryAtom dataclass

        用于权重重新计算等需要 dataclass 操作的场景。

        Args:
            data: 来自 store.get_atom 的字典

        Returns:
            MemoryAtom dataclass 实例
        """
        atom_type_str = data.get("atom_type", "episodic")
        decay_type_str = data.get("decay_type", "exponential")

        return MemoryAtomDC(
            atom_id=data.get("atom_id", ""),
            atom_type=AtomType(atom_type_str),
            content=data.get("content", ""),
            entities=data.get("entities", []),
            importance=float(data.get("importance", 0.5)),
            confidence=float(data.get("confidence", 0.5)),
            weight=float(data.get("weight", 0.5)),
            ttl_days=float(data.get("ttl_days", 7)),
            decay_type=DecayType(decay_type_str),
            reinforcement_count=int(data.get("reinforcement_count", 0)),
            source_scene=data.get("source_scene", "unknown"),
            source_id=data.get("source_id"),
            privacy_level=data.get("privacy_level", "context_sensitive"),
            status=data.get("status", "active"),
        )

    async def _upsert_qdrant(self, atom: MemoryAtomDC) -> bool:
        """将原子的 embedding 向量同步到 Qdrant

        Args:
            atom: 含有 embedding 的记忆原子

        Returns:
            True 表示写入成功或 Qdrant 不可用
        """
        if not atom.embedding:
            return True
        payload: dict[str, Any] = {
            "atom_id": atom.atom_id,
            "atom_type": _convert_atom_type(atom.atom_type),
            "weight": atom.weight,
            "importance": atom.importance,
            "confidence": atom.confidence,
            "status": atom.status,
            "source_scene": atom.source_scene,
            "source_id": atom.source_id,
            "privacy_level": atom.privacy_level,
        }
        return await self.store.qdrant.upsert_atom_vector(
            point_id=atom.atom_id,
            vector=atom.embedding,
            payload=payload,
        )

    async def _write_episodic_detail(self, atom_id: str, detail: EpisodicDetail) -> None:
        """写入情景记忆扩展详情"""
        try:
            with memory_db:
                EpisodicDetailModel.get_or_create(
                    id=atom_id,
                    defaults={
                        "atom": atom_id,
                        "event_time": (to_datetime(detail.event_time) if detail.event_time else None),
                        "participants": (
                            json.dumps(detail.participants, ensure_ascii=False) if detail.participants else None
                        ),
                        "emotion_tags": (
                            json.dumps(detail.emotion_tags, ensure_ascii=False) if detail.emotion_tags else None
                        ),
                        "sensory_tags": (
                            json.dumps(detail.sensory_tags, ensure_ascii=False) if detail.sensory_tags else None
                        ),
                        "temporal_context": detail.temporal_context or None,
                    },
                )
        except Exception as e:
            logger.error(f"写入情景详情失败 ({atom_id}): {e}")

    async def _write_semantic_detail(self, atom_id: str, detail: SemanticDetail) -> None:
        """写入语义记忆扩展详情"""
        try:
            with memory_db:
                SemanticDetailModel.get_or_create(
                    id=atom_id,
                    defaults={
                        "atom": atom_id,
                        "attr_category": detail.attr_category,
                        "attr_name": detail.attr_name,
                        "attr_value": detail.attr_value,
                        "evidence_list": (
                            json.dumps(detail.evidence_list, ensure_ascii=False) if detail.evidence_list else None
                        ),
                        "evidence_counter": detail.evidence_counter,
                    },
                )
        except Exception as e:
            logger.error(f"写入语义详情失败 ({atom_id}): {e}")


# ---------------------------------------------------------------------------
# 检索器
# ---------------------------------------------------------------------------


class MemoryRetriever:
    """第3层检索器 — 向量检索 + 权重排序

    支持场景分区检索、用户记忆检索、向量相似度检索和关键词回退检索。
    所有检索结果均按 weight × similarity 综合评分排序。
    """

    def __init__(self, store: MemoryStore, graph_store: Optional[GraphStore] = None):
        """初始化检索器

        Args:
            store: MemoryStore 实例（承载 SQLite + Qdrant）
            graph_store: GraphStore 实例（可选，用于图谱关联扩展）
        """
        self.store = store
        self.graph_store = graph_store

    # ── 向量检索 ───────────────────────────────────────────

    async def retrieve_by_vector(
        self,
        query_embedding: Optional[list[float]] = None,
        query_text: str = "",
        filters: Optional[dict[str, Any]] = None,
        top_k: int = 10,
        min_weight: float = 0.0,
    ) -> list[dict[str, Any]]:
        """向量相似度检索 + 权重排序

        先通过 Qdrant 检索 top_k × 2 候选，再从 SQLite 加载完整数据，
        以 weight × similarity 综合评分重排后返回。

        Args:
            query_embedding: 查询向量（可选，与 query_text 二选一）
            query_text: 查询文本（可选，自动生成 embedding 后检索）
            filters: Qdrant 过滤条件（如 {"source_scene": "group_chat"}）
            top_k: 最终返回数量
            min_weight: 最低权重阈值

        Returns:
            检索结果字典列表，每项含原子全部字段 + final_score + similarity_score
        """
        # 0. 自动生成 query embedding
        if query_embedding is None:
            if query_text:
                query_embedding = await generate_query_embedding(query_text)
            if query_embedding is None:
                logger.debug("向量检索: 无 query_embedding，回退到关键词检索")
                kw_query = (filters or {}).get("keyword", query_text)
                return await self.keyword_search(
                    query=kw_query,
                    filters=filters,
                    limit=top_k,
                )

        # 1. Qdrant 检索（oversample 2x）
        oversample_limit = top_k * 2
        qdrant_results = await self.store.search_similar(
            query_vector=query_embedding,
            filters=filters,
            limit=oversample_limit,
        )

        if not qdrant_results:
            logger.warning("Qdrant向量检索失败或返回为空，回退到关键词检索")
            logger.debug("向量检索回退详情", filters=filters, top_k=top_k)
            kw_query = filters.get("keyword", "") if filters else ""
            return await self.keyword_search(
                query=kw_query,
                filters=filters,
                limit=top_k,
            )

        # 2. 提取 atom_id 并加载完整数据
        atom_id_to_score: dict[str, float] = {}
        for result in qdrant_results:
            payload = result.get("payload", {}) or {}
            aid = payload.get("atom_id", result.get("id"))
            if aid:
                atom_id_to_score[str(aid)] = result.get("score", 0.0)

        full_atoms = await self._fetch_atoms_by_ids(list(atom_id_to_score.keys()))

        # 3. 计算综合评分
        results: list[dict[str, Any]] = []
        for atom_data in full_atoms:
            aid = atom_data.get("atom_id", "")
            sim_score = atom_id_to_score.get(aid, 0.0)
            weight = float(atom_data.get("weight", 0.0))

            final_score = self._compute_final_score(sim_score, weight)

            if weight < min_weight:
                continue

            atom_data["similarity_score"] = sim_score
            atom_data["final_score"] = final_score
            atom_data["fade_level"] = get_fade_level(weight)
            results.append(atom_data)

        # 4. 按 final_score 排序
        results.sort(key=lambda a: a["final_score"], reverse=True)

        logger.debug(
            "向量检索完成",
            top_k=top_k,
            results_count=len(results),
            oversample_limit=oversample_limit,
        )
        return results[:top_k]

    async def retrieve_by_scene(
        self,
        source_scene: str,
        limit: int = 50,
        min_weight: float = 0.1,
    ) -> list[dict[str, Any]]:
        """按场景检索记忆（分区存储入口）

        直接从 SQLite 按 source_scene 过滤，按 weight 降序排列。

        Args:
            source_scene: 来源场景（group_chat/private_chat/dream/system）
            limit: 最大返回数量
            min_weight: 最低权重阈值

        Returns:
            符合场景和权重条件的原子字典列表
        """
        try:
            with memory_db:
                query = (
                    MemoryAtomModel.select()
                    .where(MemoryAtomModel.source_scene == source_scene)
                    .where(MemoryAtomModel.status == "active")
                    .order_by(MemoryAtomModel.weight.desc())
                    .limit(limit)
                )
                return [self._model_to_result(atom) for atom in query if atom.weight >= min_weight]
        except Exception as e:
            logger.error(f"按场景检索失败 ({source_scene}): {e}")
            return []

    async def retrieve_by_source(
        self,
        source_id: str,
        source_scene: Optional[str] = None,
        limit: int = 50,
        min_weight: float = 0.1,
    ) -> list[dict[str, Any]]:
        """按具体聊天流检索记忆。

        source_id 对应 ChatStream.stream_id，用于隔离不同群聊/私聊的本地记忆。
        """
        if not source_id:
            return []
        try:
            with memory_db:
                conditions = [
                    MemoryAtomModel.source_id == source_id,
                    MemoryAtomModel.status == "active",
                ]
                if source_scene:
                    conditions.append(MemoryAtomModel.source_scene == source_scene)
                query = (
                    MemoryAtomModel.select()
                    .where(*conditions)
                    .order_by(MemoryAtomModel.weight.desc())
                    .limit(limit)
                )
                return [self._model_to_result(atom) for atom in query if atom.weight >= min_weight]
        except Exception as e:
            logger.error(f"按来源检索失败 ({source_id}): {e}")
            return []

    async def retrieve_by_user(
        self,
        user_id: str,
        limit: int = 50,
        source_id: Optional[str] = None,
        source_scene: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """按用户检索相关记忆

        通过 entities 字段中是否包含目标 user_id 来匹配。
        SQLite LIKE 只做候选粗筛，最终使用 JSON 解析做精确匹配，避免 "12" 误命中 "123"。

        Args:
            user_id: 用户 ID
            limit: 最大返回数量

        Returns:
            匹配用户的原子字典列表，按 weight 降序
        """
        try:
            with memory_db:
                conditions = [
                    MemoryAtomModel.entities.contains(user_id),
                    MemoryAtomModel.status == "active",
                ]
                if source_id:
                    conditions.append(MemoryAtomModel.source_id == source_id)
                if source_scene:
                    conditions.append(MemoryAtomModel.source_scene == source_scene)
                query = MemoryAtomModel.select().where(*conditions).order_by(MemoryAtomModel.weight.desc())

                results: list[dict[str, Any]] = []
                for atom in query:
                    if not _entities_include_user(atom.entities, user_id):
                        continue
                    results.append(self._model_to_result(atom))
                    if len(results) >= limit:
                        break
                return results
        except Exception as e:
            logger.error(f"按用户检索失败 ({user_id}): {e}")
            return []

    async def keyword_search(
        self,
        query: str,
        filters: Optional[dict[str, Any]] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """关键词全文搜索（SQLite LIKE 回退方案）

        Args:
            query: 搜索关键词
            filters: 可选过滤条件（如 {"source_scene": "group_chat"}）
            limit: 最大返回数量

        Returns:
            匹配关键词的原子字典列表，按 weight 降序
        """
        if not query:
            return []

        try:
            with memory_db:
                conditions = [
                    MemoryAtomModel.content.contains(query),
                    MemoryAtomModel.status == "active",
                ]

                # 额外过滤条件
                if filters:
                    if "source_scene" in filters:
                        conditions.append(MemoryAtomModel.source_scene == filters["source_scene"])
                    if "source_id" in filters:
                        conditions.append(MemoryAtomModel.source_id == filters["source_id"])
                    if "atom_type" in filters:
                        conditions.append(MemoryAtomModel.atom_type == filters["atom_type"])
                    if "status" in filters:
                        conditions.append(MemoryAtomModel.status == filters["status"])

                query_result = (
                    MemoryAtomModel.select().where(*conditions).order_by(MemoryAtomModel.weight.desc()).limit(limit)
                )
                return [self._model_to_result(atom) for atom in query_result]
        except Exception as e:
            logger.error(f"关键词检索失败 ({query}): {e}")
            return []

    # ── 上下文检索 ─────────────────────────────────────────

    async def get_context_for_reply(
        self,
        stream_id: str,
        user_id: Optional[str] = None,
        scene_type: Optional[str] = None,
        max_atoms: int = 5,
        max_chars: int = 2000,
        enable_association_expansion: bool = True,
        include_sensory_tags: bool = True,
        include_global: Optional[bool] = None,
    ) -> str:
        """获取回复上下文 — 为 LLM 生成检索到的记忆文本块

        检索策略:
            - 优先该 stream 下权重最高的记忆
            - 如果指定了 user_id，同时检索该用户的记忆
            - 仅包含 fade_level 为"完整"或"摘要"的记忆
            - 按 final_score 排序，截断至 max_chars
            - 如果启用关联扩展，自动追加关联记忆
            - 如果启用感官标签增强，自动从 EpisodicDetail 加载感官/情绪/时间信息

        Args:
            stream_id: 聊天流 ID（group_id 或 private chat id）
            user_id: 用户 ID（可选，用于个性化检索）
            scene_type: 当前场景类型（group_chat/private_chat）
            max_atoms: 最大返回记忆条数
            max_chars: 返回文本的最大字符数
            enable_association_expansion: 是否启用关联扩展（默认 True）
            include_sensory_tags: 是否在格式化中插入感官/情绪/时间标签前缀（默认 True）
            include_global: 是否补充同场景全局记忆；None 时读取配置

        Returns:
            格式化的记忆文本块，可用于 LLM prompt 拼接
        """
        candidates: list[dict[str, Any]] = []

        scene = _resolve_scene_type(stream_id, scene_type)
        include_global = _global_memory_allowed(stream_id, include_global)
        blacklisted_source_ids = _global_memory_blacklist_source_ids() if include_global else set()

        # 1. 优先检索当前聊天流的本地记忆
        local_atoms = await self.retrieve_by_source(
            source_id=stream_id,
            source_scene=scene,
            limit=max_atoms * 3,
            min_weight=0.0,
        )
        candidates.extend(local_atoms)

        # 2. 配置允许时补充同场景全局记忆
        if include_global:
            scene_atoms = await self.retrieve_by_scene(
                source_scene=scene,
                limit=max_atoms * 3,
                min_weight=0.0,
            )
            privacy_filter = PrivacyFilter()
            global_atoms = [
                atom
                for atom in scene_atoms
                if atom.get("source_id") != stream_id and atom.get("source_id") not in blacklisted_source_ids
            ]
            candidates.extend(privacy_filter.filter_atoms(global_atoms, scene, stream_id))

        # 3. 如果指定了用户，补充当前聊天流内该用户的记忆
        if user_id:
            user_atoms = await self.retrieve_by_user(
                user_id=user_id,
                source_id=stream_id,
                source_scene=scene,
                limit=max_atoms * 2,
            )
            candidates.extend(user_atoms)
            if include_global:
                global_user_atoms = await self.retrieve_by_user(
                    user_id=user_id,
                    limit=max_atoms * 2,
                )
                privacy_filter = PrivacyFilter()
                global_user_atoms = [
                    atom for atom in global_user_atoms if atom.get("source_id") not in blacklisted_source_ids
                ]
                candidates.extend(privacy_filter.filter_atoms(global_user_atoms, scene, stream_id))

        if not candidates:
            return ""

        # 4. 去重（按 atom_id 去重，保留 first_score 更高的那条）
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for atom in candidates:
            aid = atom.get("atom_id", "")
            if aid not in seen:
                seen.add(aid)
                # 确保有 final_score
                if "final_score" not in atom:
                    weight = float(atom.get("weight", 0.0))
                    atom["final_score"] = weight
                unique.append(atom)

        # 5. 仅保留 fade_level ∈ {完整, 摘要}
        filtered = [a for a in unique if get_fade_level(float(a.get("weight", 0.0))) in ("完整", "摘要")]

        # 6. 按 final_score 排序
        filtered.sort(key=lambda a: a.get("final_score", 0.0), reverse=True)

        # 7. 感官标签增强（从 EpisodicDetail 表加载并注入前缀到 content）
        top_atoms = filtered[:max_atoms]
        if include_sensory_tags:
            try:
                episodic_atom_ids = [a.get("atom_id", "") for a in top_atoms if a.get("atom_type") == "episodic"]
                if episodic_atom_ids:
                    with memory_db:
                        detail_rows = EpisodicDetailModel.select().where(
                            EpisodicDetailModel.atom.in_(episodic_atom_ids)
                        )
                        tag_map: dict[str, list[str]] = {}
                        for row in detail_rows:
                            aids = row.atom
                            try:
                                sensory = json.loads(row.sensory_tags) if row.sensory_tags else []
                            except (json.JSONDecodeError, TypeError):
                                sensory = []
                            emotional = [t for t in sensory if t.startswith("emotional:")]
                            other = [t for t in sensory if not t.startswith("emotional:")]
                            prefixes: list[str] = []
                            if emotional:
                                labels = [e.split(":", 1)[1] for e in emotional]
                                prefixes.append(f"[情感: {'/'.join(labels)}]")
                            if other:
                                prefixes.append(f"[感官: {'/'.join(other)}]")
                            if row.temporal_context:
                                prefixes.append(f"[时间: {row.temporal_context}]")
                            if prefixes:
                                tag_map[aids] = prefixes

                    for atom in top_atoms:
                        aid = atom.get("atom_id", "")
                        prefixes = tag_map.get(aid)
                        if prefixes:
                            prefix_str = " ".join(prefixes)
                            orig_content = atom.get("content", "")
                            atom["content"] = f"{prefix_str} {orig_content}"
            except Exception as e:
                logger.warning("感官标签增强失败: %s", e)

        # 8. 格式化 & 截断
        formatted = self._format_atoms_for_prompt(top_atoms)
        if len(formatted) > max_chars:
            formatted = formatted[:max_chars].rsplit("\n", 1)[0]

        # 9. 关联扩展
        if enable_association_expansion and top_atoms:
            try:
                expanded = await self._expand_with_associations(top_atoms, max_depth=2)
                if expanded:
                    # 过滤也在得分范围内的关联
                    existing_ids = {a.get("atom_id", "") for a in top_atoms}
                    assoc_lines: list[str] = []
                    for i, atom in enumerate(expanded, 1):
                        aid = atom.get("atom_id", "")
                        if aid and aid not in existing_ids:
                            content = atom.get("content", "")
                            assoc_lines.append(f"[关联记忆{i}] {content}")

                    if assoc_lines:
                        assoc_text = "\n" + "\n".join(assoc_lines)
                        remaining = max_chars - len(formatted)
                        if remaining > 0:
                            if len(assoc_text) > remaining:
                                assoc_text = assoc_text[:remaining].rsplit("\n", 1)[0]
                            formatted += assoc_text
            except Exception as e:
                logger.warning("关联扩展失败 (get_context_for_reply): %s", e)

        logger.info(
            "构建记忆检索上下文",
            scene_type=scene,
            atom_count=len(candidates),
            context_chars=len(formatted),
        )
        logger.debug(
            "检索上下文详情",
            atom_types=dict(Counter(a.get("atom_type", "unknown") for a in candidates)),
        )
        return formatted

    async def get_context_for_reply_with_ids(
        self,
        stream_id: str,
        user_id: Optional[str] = None,
        scene_type: Optional[str] = None,
        max_atoms: int = 5,
        max_chars: int = 2000,
        include_sensory_tags: bool = True,
        enable_association_expansion: bool = True,
        include_global: Optional[bool] = None,
    ) -> tuple[str, list[str]]:
        """获取回复上下文同时返回 atom_ids — 与 get_context_for_reply() 逻辑一致

        与 get_context_for_reply() 相同的检索策略，但额外返回被检索到的 atom_id 列表，
        供后续反馈系统（reinforce_memory 等）使用。
        如果启用了感官标签增强，自动从 EpisodicDetail 加载感官/情绪/时间信息并注入前缀。
        如果启用了关联扩展，自动追加关联记忆。

        Args:
            stream_id: 聊天流 ID（group_id 或 private chat id）
            user_id: 用户 ID（可选，用于个性化检索）
            scene_type: 当前场景类型（group_chat/private_chat）
            max_atoms: 最大返回记忆条数
            max_chars: 返回文本的最大字符数
            include_sensory_tags: 是否在格式化中插入感官/情绪/时间标签前缀（默认 True）
            enable_association_expansion: 是否启用关联扩展（默认 True）
            include_global: 是否补充同场景全局记忆；None 时读取配置

        Returns:
            tuple[str, list[str]]: (格式化后的记忆文本块, 检索到的 atom_id 列表)
        """
        candidates: list[dict[str, Any]] = []

        scene = _resolve_scene_type(stream_id, scene_type)
        include_global = _global_memory_allowed(stream_id, include_global)
        blacklisted_source_ids = _global_memory_blacklist_source_ids() if include_global else set()

        # 1. 优先检索当前聊天流的本地记忆
        local_atoms = await self.retrieve_by_source(
            source_id=stream_id,
            source_scene=scene,
            limit=max_atoms * 3,
            min_weight=0.0,
        )
        candidates.extend(local_atoms)

        # 2. 配置允许时补充同场景全局记忆
        if include_global:
            scene_atoms = await self.retrieve_by_scene(
                source_scene=scene,
                limit=max_atoms * 3,
                min_weight=0.0,
            )
            privacy_filter = PrivacyFilter()
            global_atoms = [
                atom
                for atom in scene_atoms
                if atom.get("source_id") != stream_id and atom.get("source_id") not in blacklisted_source_ids
            ]
            candidates.extend(privacy_filter.filter_atoms(global_atoms, scene, stream_id))

        # 3. 如果指定了用户，补充当前聊天流内该用户的记忆
        if user_id:
            user_atoms = await self.retrieve_by_user(
                user_id=user_id,
                source_id=stream_id,
                source_scene=scene,
                limit=max_atoms * 2,
            )
            candidates.extend(user_atoms)
            if include_global:
                global_user_atoms = await self.retrieve_by_user(
                    user_id=user_id,
                    limit=max_atoms * 2,
                )
                privacy_filter = PrivacyFilter()
                global_user_atoms = [
                    atom for atom in global_user_atoms if atom.get("source_id") not in blacklisted_source_ids
                ]
                candidates.extend(privacy_filter.filter_atoms(global_user_atoms, scene, stream_id))

        if not candidates:
            return "", []

        # 4. 去重（按 atom_id 去重，保留 first_score 更高的那条）
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for atom in candidates:
            aid = atom.get("atom_id", "")
            if aid not in seen:
                seen.add(aid)
                # 确保有 final_score
                if "final_score" not in atom:
                    weight = float(atom.get("weight", 0.0))
                    atom["final_score"] = weight
                unique.append(atom)

        # 5. 仅保留 fade_level ∈ {完整, 摘要}
        filtered = [a for a in unique if get_fade_level(float(a.get("weight", 0.0))) in ("完整", "摘要")]

        # 6. 按 final_score 排序
        filtered.sort(key=lambda a: a.get("final_score", 0.0), reverse=True)

        # 7. 感官标签增强（从 EpisodicDetail 表加载并注入前缀到 content）
        top_atoms = filtered[:max_atoms]
        if include_sensory_tags:
            try:
                episodic_atom_ids_sensory = [
                    a.get("atom_id", "") for a in top_atoms if a.get("atom_type") == "episodic"
                ]
                if episodic_atom_ids_sensory:
                    with memory_db:
                        detail_rows = EpisodicDetailModel.select().where(
                            EpisodicDetailModel.atom.in_(episodic_atom_ids_sensory)
                        )
                        tag_map: dict[str, list[str]] = {}
                        for row in detail_rows:
                            aids = row.atom
                            try:
                                sensory = json.loads(row.sensory_tags) if row.sensory_tags else []
                            except (json.JSONDecodeError, TypeError):
                                sensory = []
                            emotional = [t for t in sensory if t.startswith("emotional:")]
                            other = [t for t in sensory if not t.startswith("emotional:")]
                            prefixes: list[str] = []
                            if emotional:
                                labels = [e.split(":", 1)[1] for e in emotional]
                                prefixes.append(f"[情感: {'/'.join(labels)}]")
                            if other:
                                prefixes.append(f"[感官: {'/'.join(other)}]")
                            if row.temporal_context:
                                prefixes.append(f"[时间: {row.temporal_context}]")
                            if prefixes:
                                tag_map[aids] = prefixes

                    for atom in top_atoms:
                        aid = atom.get("atom_id", "")
                        prefixes = tag_map.get(aid)
                        if prefixes:
                            prefix_str = " ".join(prefixes)
                            orig_content = atom.get("content", "")
                            atom["content"] = f"{prefix_str} {orig_content}"
            except Exception as e:
                logger.warning("感官标签增强失败 (get_context_for_reply_with_ids): %s", e)

        # 8. 取 top-N 并收集 atom_ids
        atom_ids: list[str] = [a.get("atom_id", "") for a in top_atoms if a.get("atom_id")]

        # 9. 格式化 & 截断
        formatted = self._format_atoms_for_prompt(top_atoms)
        if len(formatted) > max_chars:
            formatted = formatted[:max_chars].rsplit("\n", 1)[0]

        # 10. 关联扩展
        if enable_association_expansion and top_atoms:
            try:
                expanded = await self._expand_with_associations(top_atoms, max_depth=2)
                if expanded:
                    existing_ids = {a.get("atom_id", "") for a in top_atoms}
                    assoc_lines: list[str] = []
                    for i, atom in enumerate(expanded, 1):
                        aid = atom.get("atom_id", "")
                        if aid and aid not in existing_ids:
                            content = atom.get("content", "")
                            assoc_lines.append(f"[关联记忆{i}] {content}")

                    if assoc_lines:
                        assoc_text = "\n" + "\n".join(assoc_lines)
                        remaining = max_chars - len(formatted)
                        if remaining > 0:
                            if len(assoc_text) > remaining:
                                assoc_text = assoc_text[:remaining].rsplit("\n", 1)[0]
                            formatted += assoc_text
            except Exception as e:
                logger.warning("关联扩展失败 (get_context_for_reply_with_ids): %s", e)

        # 11. 图谱关联扩展
        if self.graph_store is not None and enable_association_expansion and top_atoms:
            try:
                graph_expanded = await self._expand_with_graph(atom_ids, max_depth=1)
                if graph_expanded:
                    existing_ids = set(atom_ids)
                    graph_lines: list[str] = []
                    for atom in graph_expanded:
                        aid = atom.get("atom_id", "")
                        if aid and aid not in existing_ids:
                            content = atom.get("content", "")
                            graph_lines.append(f"[关联实体] {content}")
                            existing_ids.add(aid)
                            atom_ids.append(aid)

                    if graph_lines:
                        graph_text = "\n" + "\n".join(graph_lines)
                        remaining = max_chars - len(formatted)
                        if remaining > 0:
                            if len(graph_text) > remaining:
                                graph_text = graph_text[:remaining].rsplit("\n", 1)[0]
                            formatted += graph_text
            except Exception as e:
                logger.warning("图谱关联扩展失败 (get_context_for_reply_with_ids): %s", e)

        logger.info(
            "构建带ID的记忆检索上下文",
            scene_type=scene,
            atom_count=len(candidates),
            context_chars=len(formatted),
            atom_ids_count=len(atom_ids),
        )
        logger.debug(
            "检索上下文详情（带ID）",
            atom_types=dict(Counter(a.get("atom_type", "unknown") for a in candidates)),
        )
        return formatted, atom_ids

    async def get_atom_ids_for_reply(
        self,
        stream_id: str,
        user_id: Optional[str] = None,
        scene_type: Optional[str] = None,
        max_atoms: int = 5,
        include_global: Optional[bool] = None,
    ) -> list[str]:
        """仅返回检索到的 atom_ids（无格式化文本）

        轻量级方法，返回被检索到的记忆原子 ID 列表，用于需要在生成回复
        之前预知哪些原子将被检索（如反馈信号准备）。

        Args:
            stream_id: 聊天流 ID
            user_id: 用户 ID（可选）
            scene_type: 当前场景类型（group_chat/private_chat）
            max_atoms: 最大返回条数
            include_global: 是否补充同场景全局记忆；None 时读取配置

        Returns:
            list[str]: 检索到的 atom_id 列表
        """
        _, atom_ids = await self.get_context_for_reply_with_ids(
            stream_id=stream_id,
            user_id=user_id,
            scene_type=scene_type,
            max_atoms=max_atoms,
            include_global=include_global,
        )
        return atom_ids

    # ── 关联扩展检索 ──────────────────────────────────────────

    async def retrieve_with_associations(
        self,
        query_embedding: Optional[list[float]] = None,
        filters: Optional[dict[str, Any]] = None,
        top_k: int = 10,
        max_depth: int = 2,
    ) -> list[dict[str, Any]]:
        """向量/关键词检索 + 关联链扩展

        先执行标准检索（向量或关键词），再对 top 结果进行关联扩展，
        将关联的记忆原子合并到结果中（去重）。

        Args:
            query_embedding: 查询向量（可选，无则走关键词回退）
            filters: Qdrant 过滤条件
            top_k: 标准检索返回数量
            max_depth: 关联链最大深度（BFS）

        Returns:
            合并后的检索结果列表（含关联扩展）
        """
        # 1. 标准检索
        if query_embedding:
            results = await self.retrieve_by_vector(
                query_embedding=query_embedding,
                filters=filters,
                top_k=top_k,
            )
        else:
            results = await self.keyword_search(
                query=(filters or {}).get("keyword", ""),
                filters=filters,
                limit=top_k,
            )

        if not results:
            return []

        # 2. 关联扩展
        expanded = await self._expand_with_associations(results, max_depth)
        if not expanded:
            return results

        # 3. 合并去重
        existing_ids = {a.get("atom_id", "") for a in results}
        merged = list(results)
        for atom in expanded:
            aid = atom.get("atom_id", "")
            if aid and aid not in existing_ids:
                existing_ids.add(aid)
                atom["source"] = "association_expansion"
                merged.append(atom)

        logger.info(
            "关联扩展检索完成",
            base_count=len(results),
            expanded_count=len(expanded),
            merged_count=len(merged),
        )
        return merged

    async def _expand_with_associations(
        self,
        atoms: list[dict[str, Any]],
        max_depth: int = 2,
    ) -> list[dict[str, Any]]:
        """对检索结果执行关联链扩展，返回关联原子的完整数据

        对每个原子调用 AtomAssociationStore.get_chain() 获取关联原子 ID，
        批量加载完整数据后返回。

        Args:
            atoms: 检索结果原子列表
            max_depth: BFS 最大深度

        Returns:
            关联原子的完整数据列表
        """
        try:
            from src.memory.atom_association import AtomAssociationStore

            assoc_store = AtomAssociationStore()
            chain_set: set[str] = set()
            chain_order: dict[str, dict] = {}

            for atom in atoms:
                aid = atom.get("atom_id", "")
                if not aid:
                    continue
                chain = assoc_store.get_chain(aid, max_depth=max_depth)
                for item in chain:
                    cid = item["atom_id"]
                    if cid not in chain_set:
                        chain_set.add(cid)
                        chain_order[cid] = item

            if not chain_set:
                return []

            # 批量加载原子完整数据
            chain_data = await self._fetch_atoms_by_ids(list(chain_set))

            # 附加上下文信息
            for atom_data in chain_data:
                aid = atom_data.get("atom_id", "")
                info = chain_order.get(aid, {})
                atom_data["association_type"] = info.get("association_type", "")
                atom_data["association_depth"] = info.get("depth", 0)
                atom_data["source"] = "association_expansion"

            return chain_data
        except ImportError:
            return []
        except Exception as e:
            logger.warning("关联扩展失败: %s", e)
            return []

    # ── 图谱关联扩展 ────────────────────────────────────────

    async def _expand_with_graph(
        self,
        atom_ids: list[str],
        max_depth: int = 1,
    ) -> list[dict[str, Any]]:
        """通过图谱 BFS 遍历扩展关联记忆原子

        对每个 atom_id 调用 graph_store.get_related_atoms() 获取图结构中的
        关联原子 ID，批量加载完整数据后返回。

        Args:
            atom_ids: 基准原子 ID 列表
            max_depth: 图遍历最大深度

        Returns:
            关联原子的完整数据列表（已去重、已过滤掉基准原子）
        """
        if not self.graph_store or not atom_ids:
            return []

        try:
            base_set: set[str] = set(atom_ids)
            related_ids: set[str] = set()

            for aid in atom_ids:
                ids = self.graph_store.get_related_atoms(aid, max_depth=max_depth)
                related_ids.update(ids)

            # 移除基准原子自身
            new_ids = list(related_ids - base_set)
            if not new_ids:
                return []

            # 批量加载完整数据（非 atom_id 的值会被 _fetch_atoms_by_ids 静默忽略）
            return await self._fetch_atoms_by_ids(new_ids)
        except Exception as e:
            logger.warning("图谱关联扩展失败: %s", e)
            return []

    # ── 跨场景检索 ──────────────────────────────────────────

    async def get_cross_scene_context(
        self,
        scene_type: str,
        stream_id: str,
        user_id: str = "",
        max_atoms: int = 3,
        max_chars: int = 400,
        cross_scene_atoms: int = 5,
    ) -> str:
        """跨场景记忆检索 — 从其他场景获取记忆并应用隐私过滤

        与 get_context_for_reply 配合使用：先从当前场景获取记忆，
        再通过此方法获取来自其他场景的跨场景记忆。

        工作流程:
            1. 确定目标场景和另一场景
            2. 从另一场景检索权重较高的记忆
            3. 如果提供了 user_id，补充该用户的记忆（可能跨场景）
            4. 去重
            5. 应用 PrivacyFilter 三级隐私过滤
            6. 排序后返回格式化文本

        Args:
            scene_type: 当前场景类型（"group_chat" 或 "private_chat"）
            stream_id: 聊天流 ID
            user_id: 用户 ID（私聊时必须传入）
            max_atoms: 最终返回的最大记忆条数
            max_chars: 返回文本的最大字符数
            cross_scene_atoms: 跨场景检索的候选数量

        Returns:
            格式化后的跨场景记忆文本，无可返回的内容时返回空字符串
        """
        try:
            target_scene = "group_chat" if "group" in str(scene_type) else "private_chat"
            if not _global_memory_allowed(stream_id):
                return ""

            target_scope = stream_id
            blacklisted_source_ids = _global_memory_blacklist_source_ids()

            # 另一场景
            other_scene = "private_chat" if target_scene == "group_chat" else "group_chat"

            cross_candidates: list[AtomDict] = []

            # 1. 从另一场景检索记忆
            other_atoms = await self.retrieve_by_scene(
                source_scene=other_scene,
                limit=cross_scene_atoms * 3,
                min_weight=0.0,
            )
            cross_candidates.extend(
                atom for atom in other_atoms if atom.get("source_id") not in blacklisted_source_ids
            )

            # 2. 补充该用户跨场景的记忆
            if user_id:
                user_atoms = await self.retrieve_by_user(
                    user_id=user_id,
                    source_scene=other_scene,
                    limit=cross_scene_atoms * 2,
                )
                cross_candidates.extend(
                    atom for atom in user_atoms if atom.get("source_id") not in blacklisted_source_ids
                )

            if not cross_candidates:
                return ""

            # 3. 按 atom_id 去重
            seen: set[str] = set()
            unique: list[AtomDict] = []
            for atom in cross_candidates:
                aid = atom.get("atom_id", "")
                if aid and aid not in seen:
                    seen.add(aid)
                    unique.append(atom)

            # 4. 隐私过滤
            privacy_filter = PrivacyFilter()
            filtered = privacy_filter.filter_atoms(
                unique,
                target_scene,
                target_scope,
            )

            if not filtered:
                return ""

            # 5. 按权重排序
            for atom in filtered:
                if "final_score" not in atom:
                    atom["final_score"] = float(atom.get("weight", 0.0))
            filtered.sort(key=lambda a: a.get("final_score", 0.0), reverse=True)

            # 6. 取 top-N 并格式化
            top = filtered[:cross_scene_atoms]
            formatted = self._format_atoms_for_prompt(top)
            if len(formatted) > max_chars:
                formatted = formatted[:max_chars].rsplit("\n", 1)[0]

            logger.info(
                "跨场景检索完成",
                target_scene=target_scene,
                other_scene=other_scene,
                total_candidates=len(unique),
                after_filter=len(filtered),
                result_chars=len(formatted),
            )

            # 如果跨场景检索结果为空字符串，也记录调试日志
            if formatted:
                logger.debug(
                    "跨场景记忆详情",
                    scene_type=target_scene,
                    atom_ids=list(seen),
                )

            return formatted

        except Exception as e:
            logger.error(f"跨场景检索失败: {e}")
            return ""

    # ── 内部方法 ───────────────────────────────────────────

    async def _fetch_atoms_by_ids(self, atom_ids: list[str]) -> list[dict[str, Any]]:
        """批量根据 atom_id 从 SQLite 加载完整原子数据

        Args:
            atom_ids: 原子 ID 列表

        Returns:
            原子字典列表（按 store._atom_to_dict 格式）
        """
        if not atom_ids:
            return []

        results: list[dict[str, Any]] = []
        with memory_db:
            query = MemoryAtomModel.select().where(MemoryAtomModel.atom_id.in_(atom_ids))
            for model_instance in query:
                results.append(self._model_to_result(model_instance))

        # 保持与输入 atom_ids 相同的顺序
        id_order = {aid: i for i, aid in enumerate(atom_ids)}
        results.sort(key=lambda r: id_order.get(r.get("atom_id", ""), 999))
        return results

    @staticmethod
    def _model_to_result(model_instance: MemoryAtomModel) -> dict[str, Any]:
        """将 Peewee 模型实例转为检索结果字典

        Args:
            model_instance: MemoryAtomModel 实例

        Returns:
            包含原子全部字段的字典
        """
        data: dict[str, Any] = {
            "atom_id": model_instance.atom_id,
            "atom_type": model_instance.atom_type,
            "content": model_instance.content,
            "importance": model_instance.importance,
            "confidence": model_instance.confidence,
            "weight": model_instance.weight,
            "ttl_days": model_instance.ttl_days,
            "decay_type": model_instance.decay_type,
            "reinforcement_count": model_instance.reinforcement_count,
            "source_scene": model_instance.source_scene,
            "source_id": model_instance.source_id,
            "privacy_level": model_instance.privacy_level,
            "status": model_instance.status,
            "fade_level": get_fade_level(model_instance.weight),
        }

        # 时间字段
        if model_instance.created_at:
            data["created_at"] = model_instance.created_at.isoformat()
        if model_instance.last_accessed_at:
            data["last_accessed_at"] = model_instance.last_accessed_at.isoformat()
        if model_instance.last_reinforced_at:
            data["last_reinforced_at"] = model_instance.last_reinforced_at.isoformat()

        # entities: 反序列化 JSON
        if model_instance.entities:
            try:
                data["entities"] = json.loads(model_instance.entities)
            except (json.JSONDecodeError, TypeError):
                data["entities"] = model_instance.entities
        else:
            data["entities"] = []

        logger.debug("模型转结果", atom_id=model_instance.atom_id, atom_type=data.get("atom_type"))

        # trace_chain_id
        if model_instance.trace_chain_id:
            data["trace_chain_id"] = model_instance.trace_chain_id

        return data

    @staticmethod
    def _compute_final_score(similarity: float, weight: float) -> float:
        """综合评分：权重 × 相似度

        Args:
            similarity: 向量余弦相似度（0.0-1.0）
            weight: 原子权重（0.0-1.0）

        Returns:
            综合评分
        """
        return weight * similarity

    @staticmethod
    def _format_atoms_for_prompt(atoms: list[AtomDict]) -> str:
        """将检索结果格式化为 LLM prompt 用的文本块

        每条记忆占一行，格式: [记忆{N}][{褪色等级}] {内容}

        Args:
            atoms: 排序后的原子字典列表

        Returns:
            格式化文本块，空列表返回空字符串
        """
        if not atoms:
            return ""

        lines: list[str] = []
        for i, atom in enumerate(atoms, 1):
            content = atom.get("content", "")
            weight = float(atom.get("weight", 0.0))
            fade = get_fade_level(weight)
            lines.append(f"[记忆{i}][{fade}] {content}")

        return "\n".join(lines)
