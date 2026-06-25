"""
编码管线 — 连接 Layer 2（BatchEncoder）到 Layer 3（MemoryWriter）

将 BatchEncoder 提取的记忆原子写入 SQLite 双层存储，
同时桥接消息摄入到 BatchEncoder 的缓冲区。

位置:
  Layer 0: 原始消息归档（MessageArchiver）
  Layer 1: 纯算法话题摘要（GroupTopicSummarizer / PrivateChatSummarizer）
  Layer 2: LLM 驱动的结构化记忆提取（BatchEncoder）
  Layer 3: 记忆持久化写入 + 检索（MemoryWriter / MemoryRetriever）

本模块（Pipeline）: 连接 Layer 2 输出到 Layer 3 写入
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from src.common.logger import get_logger
from src.manager.async_task_manager import AsyncTask
from src.memory.atom import (
    AtomType,
    DecayType,
    DEFAULT_DECAY,
    DEFAULT_TTL,
    EpisodicDetail,
    MemoryAtom as MemoryAtomDC,
    SemanticDetail,
)
from src.memory.layer2_encoder import BatchEncoder
from src.memory.layer3_retrieval import MemoryWriter
from src.memory.store import MemoryStore
from src.memory.trace_chain import TraceChainRecorder, TraceStep
from src.memory.write_ops import WriteOpLogger

logger = get_logger("memory.encoding")

# 模块级单例引用（通过 get_encoding_pipeline() 获取）
_encoding_pipeline: Optional["EncodingPipeline"] = None


def get_encoding_pipeline() -> Optional["EncodingPipeline"]:
    """获取编码管线单例

    在 main.py 中初始化 EncodingPipeline 后可用。
    返回 None 表示尚未初始化或初始化失败。
    """
    return _encoding_pipeline


class EncodingPipeline:
    """编码管线 — 连接 Layer 2 编码输出到 Layer 3 记忆写入

    职责:
        1. 接收外部消息并送入 BatchEncoder 缓冲区
        2. 定时触发编码周期，将就绪流编码为记忆原子
        3. 将编码结果通过 MemoryWriter 写入 SQLite

    使用方式:
        pipeline = EncodingPipeline(store)
        await pipeline.ingest("group_123", "user_1", "小明", "今天天气真好", time.time())
        result = await pipeline.run_cycle()
    """

    def __init__(
        self,
        store: MemoryStore,
        trigger_count: int = 10,
        trigger_seconds: int = 300,
        op_logger: Optional[WriteOpLogger] = None,
    ) -> None:
        """初始化编码管线

        Args:
            store: MemoryStore 实例
            trigger_count: 累积多少条消息后触发编码（默认 10）
            trigger_seconds: 距离上次触发超过多少秒后强制触发（默认 300）
            op_logger: WriteOpLogger 实例，用于写操作追踪和一致性协调
        """
        self.encoder = BatchEncoder(
            store=store,
            trigger_count=trigger_count,
            trigger_seconds=trigger_seconds,
        )
        self.writer = MemoryWriter(store, op_logger=op_logger)
        self.trace_recorder: Optional[TraceChainRecorder] = None

        global _encoding_pipeline
        _encoding_pipeline = self

        logger.info(
            f"EncodingPipeline 初始化完成 | trigger_count={trigger_count} trigger_seconds={trigger_seconds}",
        )

    def set_trace_recorder(self, recorder: TraceChainRecorder) -> None:
        """设置追溯链记录器

        Args:
            recorder: TraceChainRecorder 实例
        """
        self.trace_recorder = recorder
        logger.info("TraceChainRecorder 已设置")

    async def ingest(
        self,
        stream_id: str,
        user_id: str,
        speaker: str,
        content: str,
        timestamp: float,
        stream_type: str = "group_chat",
    ) -> None:
        """摄入一条消息到编码缓冲区

        Args:
            stream_id: 聊天流 ID（群号 / 用户ID）
            user_id: 发送者用户 ID
            speaker: 发送者显示名称
            content: 消息文本内容
            timestamp: Unix 时间戳（秒）
            stream_type: 流类型（group_chat / private_chat）
        """
        self.encoder.set_stream_type(stream_id, stream_type)
        await self.encoder.ingest_message(
            stream_id=stream_id,
            user_id=user_id,
            speaker=speaker,
            content=content,
            timestamp=datetime.fromtimestamp(timestamp),
        )
        logger.debug(
            "消息摄入编码管线",
            stream_id=stream_id,
            stream_type=stream_type,
        )

    async def run_cycle(self) -> dict[str, Any]:
        """执行一次编码周期

        流程:
            1. 调用 encoder.encode_all_ready() 对所有就绪流编码
            2. 将每个编码结果构建为 MemoryAtom dataclass
            3. 通过 writer.write_atom() 写入 SQLite 存储

        Returns:
            统计字典，包含 streams_processed, atoms_written, errors
        """
        stats: dict[str, Any] = {
            "streams_processed": 0,
            "atoms_written": 0,
            "errors": 0,
            "streams": {},
        }

        # 关联构建收集容器
        written_atoms: list[Any] = []
        stream_map: dict[str, str] = {}

        logger.debug(
            "开始编码周期",
            buffer_count=len(self.encoder.buffers),
        )

        try:
            encoded = await self.encoder.encode_all_ready()

            if not encoded:
                logger.debug("编码周期：无就绪流")
                return stats

            stats["streams_processed"] = len(encoded)

            for stream_id, atoms in encoded.items():
                stream_atoms_written = 0
                for content, atom_type, detail in atoms:
                    try:
                        atom, semantic_detail, episodic_detail = self._build_atom(
                            content=content,
                            atom_type=atom_type,
                            detail=detail,
                            source_scene=("private_chat" if "_private_" in str(stream_id) else "group_chat"),
                        )

                        if self.trace_recorder is not None:
                            self.trace_recorder.record(
                                TraceStep(
                                    atom_id=atom.atom_id,
                                    step_order=1,
                                    agent_name="Layer2Encoder",
                                    operation="extract",
                                    input_source=content,
                                    output_summary=atom.content,
                                    confidence_decay=atom.confidence,
                                )
                            )

                        # ── 客观性校验 ─────────────────────────────────────────
                        try:
                            from src.memory.objectivity_check import ObjectivityChecker

                            checker = ObjectivityChecker(self.writer.store)
                            check_result = await checker.check_before_write(
                                atom,
                                trace_recorder=self.trace_recorder,
                            )

                            if check_result.recommendation == "reject":
                                logger.info(
                                    "客观性校验: 跳过原子 | atom_id=%s type=%s reason=%s",
                                    atom.atom_id,
                                    atom_type.value,
                                    "噪声" if check_result.noise else "低一致性",
                                )
                                continue

                            # 使用调整后的原子（置信度可能已被修改）
                            if check_result.atom is not None:
                                atom = check_result.atom

                            # 记录冲突观察（含正确的 atom_b_id）
                            for conflict in check_result.conflicts:
                                try:
                                    conflict.new_atom_id = atom.atom_id
                                    await checker.record_conflict(conflict)
                                except Exception as exc:
                                    logger.warning("记录冲突失败: %s", exc, exc_info=True)
                        except ImportError:
                            pass
                        except Exception as exc:
                            logger.warning("客观性校验异常: %s", exc)
                            continue

                        if episodic_detail and episodic_detail.sensory_tags:
                            logger.debug(
                                "感官标签",
                                atom_id=atom.atom_id,
                                sensory_tags=episodic_detail.sensory_tags,
                                temporal_context=episodic_detail.temporal_context,
                            )

                        await self.writer.write_atom(
                            atom=atom,
                            semantic_detail=semantic_detail,
                            episodic_detail=episodic_detail,
                        )

                        if self.trace_recorder is not None:
                            self.trace_recorder.record(
                                TraceStep(
                                    atom_id=atom.atom_id,
                                    step_order=3,
                                    agent_name="MemoryWriter",
                                    operation="write",
                                    input_source=atom.atom_id,
                                    output_summary="stored in SQLite+Qdrant",
                                    confidence_decay=0.0,
                                )
                            )

                        if atom.atom_type == AtomType.PREFERENCE and atom.entities:
                            try:
                                from src.memory.user_profile import ProfileBuilder, ProfileStore

                                ps = ProfileStore()
                                pb = ProfileBuilder(ps)
                                for entity in atom.entities:
                                    pb.update_profile_from_atom(entity, atom)
                            except Exception:
                                pass

                        # 情景原子感官数据 → 画像 mood_history
                        if (
                            atom.atom_type == AtomType.EPISODIC
                            and episodic_detail is not None
                            and (episodic_detail.sensory_tags or episodic_detail.emotion_tags)
                        ):
                            try:
                                from src.memory.user_profile import ProfileBuilder, ProfileStore

                                ps = ProfileStore()
                                pb = ProfileBuilder(ps)
                                for entity in atom.entities:
                                    pb.update_profile_from_atom(entity, atom)
                            except Exception:
                                pass
                        # 收集已写入原子供关联构建
                        written_atoms.append(atom)
                        stream_map[atom.atom_id] = stream_id
                        stream_atoms_written += 1
                    except Exception as exc:
                        logger.error(
                            f"写入原子失败 | stream={stream_id} type={atom_type.value} error={exc}",
                        )
                        stats["errors"] += 1

                stats["atoms_written"] += stream_atoms_written
                stats["streams"][stream_id] = stream_atoms_written

            if stats["atoms_written"] > 0 or stats["errors"] > 0:
                logger.info(
                    f"编码周期完成 | streams={stats['streams_processed']} "
                    f"atoms={stats['atoms_written']} errors={stats['errors']}",
                )

        except Exception as exc:
            logger.error(f"编码周期异常 | error={exc}")
            stats["errors"] += 1

        logger.info(
            "编码周期完成",
            encoded_atoms=stats["atoms_written"],
            failed_atoms=stats["errors"],
        )

        if stats["atoms_written"] > 0:
            try:
                from src.memory.conflict_arbitration import ConflictArbiter

                arbiter = ConflictArbiter(self.writer.store)
                resolved = await arbiter.check_and_resolve()
                if resolved > 0:
                    logger.info(
                        "冲突仲裁: 自动解决 %d 组冲突 (编码周期后)",
                        resolved,
                    )
            except ImportError:
                logger.debug("冲突仲裁模块未加载")
            except Exception as exc:
                logger.warning("冲突仲裁异常: %s", exc)

        # ── 原子关联构建 ──────────────────────────────────────
        if stats["atoms_written"] > 0 and written_atoms:
            try:
                from src.memory.atom_association import AtomAssociationStore

                assoc_store = AtomAssociationStore()
                created = assoc_store.build_from_batch(written_atoms, stream_map)
                if created > 0:
                    logger.info("记忆关联: 新增 %d 条原子关联 (编码周期后)", created)
            except ImportError:
                logger.debug("原子关联模块未加载")
            except Exception as exc:
                logger.warning("原子关联构建异常: %s", exc)

        return stats

    def _build_atom(
        self,
        content: str,
        atom_type: AtomType,
        detail: dict[str, Any],
        source_scene: str,
    ) -> tuple[MemoryAtomDC, Optional[SemanticDetail], Optional[EpisodicDetail]]:
        """从编码结果构建 MemoryAtom dataclass 及可选的扩展详情

        Args:
            content: 记忆内容
            atom_type: 原子类型
            detail: 额外详情字典（来自 LLM 编码结果）
            source_scene: 来源场景（group_chat / private_chat）

        Returns:
            (MemoryAtom, SemanticDetail|None, EpisodicDetail|None) 三元组。
            SemanticDetail 仅对 PREFERENCE 和 FACTUAL 类型且 detail 含 attr_name 时构建。
            EpisodicDetail 仅对 EPISODIC 类型时构建。
        """
        importance = detail.get("importance", 0.5)
        if not isinstance(importance, (int, float)):
            importance = 0.5

        entities = detail.get("entities", [])
        if not isinstance(entities, list):
            entities = []

        atom_id = str(uuid4())

        atom = MemoryAtomDC(
            atom_id=atom_id,
            atom_type=atom_type,
            content=content,
            entities=entities,
            importance=max(0.0, min(1.0, float(importance))),
            confidence=0.7,
            weight=0.5,
            ttl_days=DEFAULT_TTL.get(atom_type, 7),
            decay_type=DEFAULT_DECAY.get(atom_type, DecayType.EXPONENTIAL),
            source_scene=source_scene,
            privacy_level="context_sensitive",
            status="active",
            embedding=None,
        )

        semantic_detail: Optional[SemanticDetail] = None
        if atom_type in (AtomType.PREFERENCE, AtomType.FACTUAL):
            attr_name = detail.get("attr_name", "")
            if attr_name:
                attr_category = detail.get("attr_category", "general")
                attr_value = detail.get("attr_value", "")
                semantic_detail = SemanticDetail(
                    atom_id=atom_id,
                    attr_category=str(attr_category),
                    attr_name=str(attr_name),
                    attr_value=str(attr_value),
                )
                atom.semantic_detail = semantic_detail

        episodic_detail: Optional[EpisodicDetail] = None
        if atom_type == AtomType.EPISODIC:
            sensory_tags = detail.get("sensory_tags") or []
            temporal_context = detail.get("temporal_context", "")
            episodic_detail = EpisodicDetail(
                atom_id=atom_id,
                participants=detail.get("participants", []),
                emotion_tags=detail.get("emotion_tags", []),
                sensory_tags=list(sensory_tags),
                temporal_context=str(temporal_context),
            )
            atom.episodic_detail = episodic_detail

        return atom, semantic_detail, episodic_detail


class EncodingTask(AsyncTask):
    """记忆编码定期任务

    按固定时间间隔调用 EncodingPipeline.run_cycle()，
    将累积的消息编码为记忆原子并写入存储。
    """

    def __init__(self, pipeline: EncodingPipeline, interval: int = 300):
        super().__init__(task_name="记忆编码扫描", run_interval=interval)
        self._pipeline = pipeline

    async def run(self) -> None:
        """执行一次编码周期"""
        try:
            stats = await self._pipeline.run_cycle()
            if stats.get("atoms_written", 0) > 0:
                logger.info(
                    f"记忆编码任务 | 流数={stats['streams_processed']} 原子数={stats['atoms_written']}",
                )
        except Exception as exc:
            logger.error(f"记忆编码任务异常 | error={exc}")
