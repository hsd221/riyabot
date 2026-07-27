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

from dataclasses import asdict, dataclass
from datetime import datetime
import json
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
    update_weight,
)
from src.memory.layer2_encoder import (
    SOURCE_IDENTITIES_DETAIL_KEY,
    SOURCE_MESSAGE_IDS_DETAIL_KEY,
    SOURCE_USER_IDS_DETAIL_KEY,
    BatchEncoder,
)
from src.memory.layer3_retrieval import MemoryWriter
from src.memory.schema import PendingAtomWrite, memory_db
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


def _safe_internal_text_list(value: Any) -> list[str]:
    """仅接受编码器内部生成的短文本列表，避免复杂对象进入证据字段。"""
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, (str, int)):
            continue
        text = str(item).strip()[:200]
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


@dataclass
class _PendingAtomWrite:
    """已通过校验但尚未成功落库的确定性写入单元。"""

    stream_id: str
    atom: MemoryAtomDC
    semantic_detail: Optional[SemanticDetail]
    episodic_detail: Optional[EpisodicDetail]
    profile_identities: list[Any]


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
        self._pending_writes: list[_PendingAtomWrite] = []
        self._pending_loaded = False
        self._outbox_enabled = True

        global _encoding_pipeline
        _encoding_pipeline = self

        logger.info(
            "EncodingPipeline 初始化完成",
            event_code="memory.encoding.pipeline_initialized",
            trigger_count=trigger_count,
            trigger_seconds=trigger_seconds,
        )

    def set_trace_recorder(self, recorder: TraceChainRecorder) -> None:
        """设置追溯链记录器

        Args:
            recorder: TraceChainRecorder 实例
        """
        self.trace_recorder = recorder
        logger.info("TraceChainRecorder 已设置", event_code="memory.encoding.trace_recorder_set")

    @staticmethod
    def _serialize_pending_write(pending: _PendingAtomWrite) -> str:
        atom_data = asdict(pending.atom)
        atom_data["atom_type"] = pending.atom.atom_type.value
        atom_data["decay_type"] = pending.atom.decay_type.value
        atom_data.pop("semantic_detail", None)
        atom_data.pop("episodic_detail", None)
        identities = [
            {
                "platform": str(getattr(identity, "platform", "legacy") or "legacy"),
                "user_id": str(getattr(identity, "user_id", "") or ""),
                "nickname": str(getattr(identity, "nickname", "") or ""),
                "cardname": str(getattr(identity, "cardname", "") or ""),
                "group_id": str(getattr(identity, "group_id", "") or ""),
                "group_name": str(getattr(identity, "group_name", "") or ""),
            }
            for identity in pending.profile_identities
        ]
        return json.dumps(
            {
                "atom": atom_data,
                "semantic_detail": asdict(pending.semantic_detail) if pending.semantic_detail is not None else None,
                "episodic_detail": asdict(pending.episodic_detail) if pending.episodic_detail is not None else None,
                "profile_identities": identities,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _deserialize_pending_write(stream_id: str, payload: str) -> _PendingAtomWrite:
        from src.memory.user_profile import PersonIdentity

        parsed = json.loads(payload)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("atom"), dict):
            raise ValueError("待写 outbox 载荷格式无效")
        atom_data = dict(parsed["atom"])
        atom_data["atom_type"] = AtomType(atom_data["atom_type"])
        atom_data["decay_type"] = DecayType(atom_data["decay_type"])
        atom = MemoryAtomDC(**atom_data)

        semantic_data = parsed.get("semantic_detail")
        semantic_detail = SemanticDetail(**semantic_data) if isinstance(semantic_data, dict) else None
        episodic_data = parsed.get("episodic_detail")
        episodic_detail = EpisodicDetail(**episodic_data) if isinstance(episodic_data, dict) else None
        profile_identities = []
        for identity_data in parsed.get("profile_identities", []):
            if not isinstance(identity_data, dict):
                continue
            try:
                profile_identities.append(PersonIdentity(**identity_data))
            except (TypeError, ValueError):
                continue
        return _PendingAtomWrite(
            stream_id=stream_id,
            atom=atom,
            semantic_detail=semantic_detail,
            episodic_detail=episodic_detail,
            profile_identities=profile_identities,
        )

    def _persist_pending_write(self, pending: _PendingAtomWrite) -> None:
        if not getattr(self, "_outbox_enabled", False):
            return
        payload = self._serialize_pending_write(pending)
        with memory_db.atomic():
            PendingAtomWrite.insert(
                atom_id=pending.atom.atom_id,
                stream_id=pending.stream_id,
                payload=payload,
                updated_at=datetime.now(),
            ).on_conflict(
                conflict_target=[PendingAtomWrite.atom_id],
                update={
                    PendingAtomWrite.stream_id: pending.stream_id,
                    PendingAtomWrite.payload: payload,
                    PendingAtomWrite.updated_at: datetime.now(),
                },
            ).execute()

    def _delete_pending_write(self, atom_id: str) -> None:
        if not getattr(self, "_outbox_enabled", False):
            return
        with memory_db.atomic():
            PendingAtomWrite.delete().where(PendingAtomWrite.atom_id == atom_id).execute()

    def _load_pending_writes(self) -> None:
        if getattr(self, "_pending_loaded", False):
            return
        if not getattr(self, "_outbox_enabled", False):
            self._pending_loaded = True
            return

        loaded_ids = {pending.atom.atom_id for pending in self._pending_writes}
        with memory_db:
            rows = list(PendingAtomWrite.select().order_by(PendingAtomWrite.created_at.asc()))
        self._pending_loaded = True
        for row in rows:
            if row.atom_id in loaded_ids:
                continue
            try:
                pending = self._deserialize_pending_write(row.stream_id, row.payload)
            except Exception:
                logger.exception(
                    "待写记忆 outbox 载荷损坏，保留记录等待人工处理",
                    event_code="memory.encoding.outbox_payload_invalid",
                    atom_id=row.atom_id,
                )
                continue
            self._pending_writes.append(pending)
            loaded_ids.add(pending.atom.atom_id)

    async def _commit_atom_write(self, pending: _PendingAtomWrite) -> None:
        """提交一个确定性原子写入，并在成功后执行画像与追溯副作用。"""
        # 写操作日志等外围步骤若在 SQLite 提交后抛错，重试时主记录可能已经存在；
        # 先按固定 atom_id 查库，让队列重试具备幂等性，避免主键冲突把任务永久卡住。
        existing = None
        get_atom = getattr(self.writer.store, "get_atom", None)
        if callable(get_atom):
            existing = await get_atom(pending.atom.atom_id)
        if existing is None:
            await self.writer.write_atom(
                atom=pending.atom,
                semantic_detail=pending.semantic_detail,
                episodic_detail=pending.episodic_detail,
            )

        if self.trace_recorder is not None:
            try:
                self.trace_recorder.record(
                    TraceStep(
                        atom_id=pending.atom.atom_id,
                        step_order=3,
                        agent_name="MemoryWriter",
                        operation="write",
                        input_source=pending.atom.atom_id,
                        output_summary="stored in SQLite+Qdrant",
                        confidence_decay=0.0,
                    )
                )
            except Exception:
                logger.warning(
                    "记忆写入追溯记录失败",
                    event_code="memory.encoding.write_trace_failed",
                    atom_id=pending.atom.atom_id,
                    exc_info=True,
                )

        if pending.atom.atom_type in (AtomType.PREFERENCE, AtomType.FACTUAL) and pending.profile_identities:
            try:
                from src.memory.user_profile import ProfileBuilder, ProfileStore

                pb = ProfileBuilder(ProfileStore())
                for identity in pending.profile_identities:
                    pb.update_profile_from_atom(identity, pending.atom)
            except Exception:
                logger.warning(
                    "语义原子画像更新失败",
                    event_code="memory.encoding.profile_update_failed",
                    atom_id=pending.atom.atom_id,
                    exc_info=True,
                )

        if (
            pending.atom.atom_type == AtomType.EPISODIC
            and pending.episodic_detail is not None
            and (pending.episodic_detail.sensory_tags or pending.episodic_detail.emotion_tags)
            and pending.profile_identities
        ):
            try:
                from src.memory.user_profile import ProfileBuilder, ProfileStore

                pb = ProfileBuilder(ProfileStore())
                for identity in pending.profile_identities:
                    pb.update_profile_from_atom(identity, pending.atom)
            except Exception:
                logger.warning(
                    "情景原子画像更新失败",
                    event_code="memory.encoding.episodic_profile_update_failed",
                    atom_id=pending.atom.atom_id,
                    exc_info=True,
                )

    async def ingest(
        self,
        stream_id: str,
        user_id: str,
        speaker: str,
        content: str,
        timestamp: float,
        stream_type: str = "group_chat",
        message_id: Optional[str] = None,
        platform: str = "",
        nickname: str = "",
        cardname: str = "",
        group_id: str = "",
        group_name: str = "",
    ) -> None:
        """摄入一条消息到编码缓冲区

        Args:
            stream_id: 聊天流 ID（群号 / 用户ID）
            user_id: 发送者用户 ID
            speaker: 发送者显示名称
            content: 消息文本内容
            timestamp: Unix 时间戳（秒）
            stream_type: 流类型（group_chat / private_chat）
            message_id: 原始消息 ID（可选，用于缓冲去重）
        """
        self.encoder.set_stream_type(stream_id, stream_type)
        await self.encoder.ingest_message(
            stream_id=stream_id,
            user_id=user_id,
            speaker=speaker,
            content=content,
            timestamp=datetime.fromtimestamp(timestamp),
            message_id=message_id,
            platform=platform,
            nickname=nickname or speaker,
            cardname=cardname,
            group_id=group_id,
            group_name=group_name,
        )
        logger.debug(
            "消息摄入编码管线",
            event_code="memory.encoding.message_ingested",
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

        # Layer2 成功后原始消息已从缓冲确认；写库失败必须保留确定性的原子对象，
        # 否则下一轮没有任何载体可重试。启动后先恢复持久化 outbox，再处理旧失败项。
        self._load_pending_writes()
        pending_writes = list(getattr(self, "_pending_writes", []))
        self._pending_writes = []
        for pending in pending_writes:
            try:
                await self._commit_atom_write(pending)
                self._delete_pending_write(pending.atom.atom_id)
                written_atoms.append(pending.atom)
                stream_map[pending.atom.atom_id] = pending.stream_id
                stats["atoms_written"] += 1
                stats["streams"][pending.stream_id] = stats["streams"].get(pending.stream_id, 0) + 1
            except Exception:
                self._pending_writes.append(pending)
                stats["errors"] += 1
                logger.exception(
                    "重试写入记忆原子失败，继续保留队列",
                    event_code="memory.encoding.atom_write_retry_failed",
                    stream_id=pending.stream_id,
                    atom_id=pending.atom.atom_id,
                )

        logger.debug(
            "开始编码周期",
            event_code="memory.encoding.cycle_started",
            buffer_count=len(self.encoder.buffers),
        )

        try:
            encoded = await self.encoder.encode_all_ready()

            if not encoded:
                logger.debug("编码周期无就绪流", event_code="memory.encoding.no_ready_stream")

            stats["streams_processed"] = len(encoded)

            for stream_id, atoms in encoded.items():
                stream_atoms_written = 0
                for content, atom_type, detail in atoms:
                    try:
                        buffer = self.encoder.get_buffer(stream_id)
                        source_scene = buffer.stream_type if buffer is not None else "group_chat"
                        atom, semantic_detail, episodic_detail = self._build_atom(
                            content=content,
                            atom_type=atom_type,
                            detail=detail,
                            source_scene=source_scene,
                            source_id=stream_id,
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
                                    "客观性校验拒绝记忆原子",
                                    event_code="memory.encoding.objectivity_rejected",
                                    atom_id=atom.atom_id,
                                    atom_type=atom_type.value,
                                    reason="noise" if check_result.noise else "low_consistency",
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
                                except Exception:
                                    logger.warning(
                                        "记忆冲突记录失败",
                                        event_code="memory.encoding.conflict_record_failed",
                                        atom_id=atom.atom_id,
                                        exc_info=True,
                                    )
                        except ImportError:
                            pass
                        except Exception:
                            logger.warning(
                                "客观性校验异常",
                                event_code="memory.encoding.objectivity_check_failed",
                                exc_info=True,
                            )
                            continue

                        if episodic_detail and episodic_detail.sensory_tags:
                            logger.debug(
                                "感官标签",
                                event_code="memory.encoding.sensory_tags",
                                atom_id=atom.atom_id,
                                sensory_tags=episodic_detail.sensory_tags,
                                temporal_context=episodic_detail.temporal_context,
                            )

                        # 画像冲突排序必须使用实际写入的权重，而不是构建原子的默认 0.5。
                        if atom.weight == 0.5:
                            atom = update_weight(atom)

                        profile_identities = self._profile_target_identities(atom, detail)
                        pending = _PendingAtomWrite(
                            stream_id=stream_id,
                            atom=atom,
                            semantic_detail=semantic_detail,
                            episodic_detail=episodic_detail,
                            profile_identities=profile_identities,
                        )
                        try:
                            self._persist_pending_write(pending)
                        except Exception:
                            self._pending_writes.append(pending)
                            raise
                        try:
                            await self._commit_atom_write(pending)
                            self._delete_pending_write(pending.atom.atom_id)
                        except Exception:
                            # Layer2 已确认并移除了原消息，必须保存这个固定 atom_id 的写入单元；
                            # 下一轮直接重试落库，不能重新跑 LLM，也不能重复已成功的同批原子。
                            self._pending_writes.append(pending)
                            raise

                        # 收集已写入原子供关联构建
                        written_atoms.append(atom)
                        stream_map[atom.atom_id] = stream_id
                        stream_atoms_written += 1
                    except Exception:
                        logger.exception(
                            "编码结果写入记忆原子失败",
                            event_code="memory.encoding.atom_write_failed",
                            stream_id=stream_id,
                            atom_type=atom_type.value,
                        )
                        stats["errors"] += 1

                stats["atoms_written"] += stream_atoms_written
                stats["streams"][stream_id] = stream_atoms_written

            if stats["atoms_written"] > 0 or stats["errors"] > 0:
                logger.info(
                    "编码周期写入阶段完成",
                    event_code="memory.encoding.cycle_write_completed",
                    streams_processed=stats["streams_processed"],
                    atoms_written=stats["atoms_written"],
                    errors=stats["errors"],
                )

        except Exception:
            logger.exception("编码周期异常", event_code="memory.encoding.cycle_failed")
            stats["errors"] += 1

        logger.info(
            "编码周期完成",
            event_code="memory.encoding.cycle_completed",
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
                        "冲突仲裁完成",
                        event_code="memory.encoding.conflict_arbitration_completed",
                        resolved_count=resolved,
                    )
            except ImportError:
                logger.debug("冲突仲裁模块未加载", event_code="memory.encoding.conflict_arbitration_unavailable")
            except Exception:
                logger.warning(
                    "冲突仲裁异常",
                    event_code="memory.encoding.conflict_arbitration_failed",
                    exc_info=True,
                )

        # ── 原子关联构建 ──────────────────────────────────────
        if stats["atoms_written"] > 0 and written_atoms:
            try:
                from src.memory.atom_association import AtomAssociationStore

                assoc_store = AtomAssociationStore()
                created = assoc_store.build_from_batch(written_atoms, stream_map)
                if created > 0:
                    logger.info(
                        "记忆原子关联构建完成",
                        event_code="memory.encoding.association_completed",
                        created_count=created,
                    )
            except ImportError:
                logger.debug("原子关联模块未加载", event_code="memory.encoding.association_unavailable")
            except Exception:
                logger.warning("原子关联构建异常", event_code="memory.encoding.association_failed", exc_info=True)

        return stats

    @staticmethod
    def _profile_target_entities(atom: MemoryAtomDC, detail: dict[str, Any]) -> list[str]:
        """只允许本批真实消息发送者触发画像更新，避免 LLM 伪造 entities 串写画像。"""
        return [identity.user_id for identity in EncodingPipeline._profile_target_identities(atom, detail)]

    @staticmethod
    def _profile_target_identities(atom: MemoryAtomDC, detail: dict[str, Any]) -> list[Any]:
        """从编码器内部元数据恢复可验证的平台人物身份。"""
        from src.memory.user_profile import PersonIdentity

        raw_identities = detail.get(SOURCE_IDENTITIES_DETAIL_KEY, [])
        identities: list[PersonIdentity] = []
        if isinstance(raw_identities, list):
            for raw_identity in raw_identities:
                if not isinstance(raw_identity, dict):
                    continue
                try:
                    identities.append(
                        PersonIdentity(
                            platform=str(raw_identity.get("platform") or "legacy"),
                            user_id=str(raw_identity.get("user_id") or ""),
                            nickname=str(raw_identity.get("nickname") or ""),
                            cardname=str(raw_identity.get("cardname") or ""),
                            group_id=str(raw_identity.get("group_id") or ""),
                            group_name=str(raw_identity.get("group_name") or ""),
                        )
                    )
                except ValueError:
                    continue

        if not identities:
            source_user_ids = detail.get(SOURCE_USER_IDS_DETAIL_KEY, [])
            if not isinstance(source_user_ids, list):
                return []
            for user_id in source_user_ids:
                normalized = str(user_id).strip()
                if normalized:
                    identities.append(PersonIdentity(platform="legacy", user_id=normalized))

        explicit_subject = str(detail.get("subject_user_id") or "").strip()
        atom_entities = {str(entity).strip() for entity in atom.entities if str(entity).strip()}
        target_user_ids = {explicit_subject} if explicit_subject else atom_entities
        targets: list[PersonIdentity] = []
        seen: set[str] = set()
        for identity in identities:
            if identity.user_id not in target_user_ids or identity.profile_id in seen:
                continue
            targets.append(identity)
            seen.add(identity.profile_id)

        # 当一条属性同时指向多个发送者时，无法安全判定属于谁。
        return targets if len(targets) == 1 else []

    def _build_atom(
        self,
        content: str,
        atom_type: AtomType,
        detail: dict[str, Any],
        source_scene: str,
        source_id: str = "",
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
            source_id=source_id or None,
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
                targets = self._profile_target_identities(atom, detail)
                evidence_list = _safe_internal_text_list(detail.get(SOURCE_MESSAGE_IDS_DETAIL_KEY))
                semantic_detail = SemanticDetail(
                    atom_id=atom_id,
                    attr_category=str(attr_category),
                    attr_name=str(attr_name),
                    attr_value=str(attr_value),
                    subject_key=targets[0].profile_id if targets else "",
                    evidence_list=evidence_list,
                    evidence_counter=max(1, len(evidence_list)),
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
                    "记忆编码任务完成",
                    event_code="memory.encoding.task_completed",
                    streams_processed=stats["streams_processed"],
                    atoms_written=stats["atoms_written"],
                )
        except Exception:
            logger.exception("记忆编码任务异常", event_code="memory.encoding.task_failed")
