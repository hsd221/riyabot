"""记忆存储层 — MemoryStore 统一封装 + Qdrant 向量索引管理

提供 SQLite (源数据) + Qdrant (向量索引) 双层存储的统一入口。
"""

import datetime
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from src.common.logger import get_logger
from src.memory.schema import (
    AtomAssociationModel,
    ConflictObservation,
    EpisodicDetail,
    MemoryAtom,
    MemoryTraceChain,
    RawMessageArchive,
    SemanticDetail,
    configure_memory_database,
    initialize_database,
    memory_db,
)
from src.memory.types import PayloadSchemaField

logger = get_logger("memory.store")

_QDRANT_POINT_NAMESPACE = uuid.UUID("8e9e1f74-2b30-4f33-8e9b-9b2c972a1a67")
_DATETIME_FIELDS = ("created_at", "last_accessed_at", "last_reinforced_at")


def _coerce_datetime(value: Any) -> datetime.datetime:
    """将持久层时间字段归一化为 Peewee DateTimeField 可接受的 datetime。"""
    if isinstance(value, datetime.datetime):
        return value
    if value is None:
        return datetime.datetime.now()
    if isinstance(value, (int, float)):
        return datetime.datetime.fromtimestamp(value)
    if isinstance(value, str):
        try:
            return datetime.datetime.fromisoformat(value)
        except (TypeError, ValueError):
            try:
                return datetime.datetime.fromtimestamp(float(value))
            except (TypeError, ValueError):
                logger.warning("无法解析时间字段，使用当前时间", value=value)
                return datetime.datetime.now()
    logger.warning("未知时间字段类型，使用当前时间", value_type=type(value).__name__)
    return datetime.datetime.now()


def _normalize_datetime_fields(data: dict[str, Any], *, fill_missing: bool = False) -> None:
    """原地归一化记忆原子的时间字段。"""
    for field_name in _DATETIME_FIELDS:
        if fill_missing or field_name in data:
            data[field_name] = _coerce_datetime(data.get(field_name))


# ---------------------------------------------------------------------------
# Qdrant 客户端导入（可选依赖）
# ---------------------------------------------------------------------------

try:
    from qdrant_client import QdrantClient as _QdrantClient
    from qdrant_client.http import models as qdrant_models

    QDRANT_AVAILABLE = True
except ImportError:
    QDRANT_AVAILABLE = False
    _QdrantClient = None  # type: ignore
    qdrant_models = None  # type: ignore


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass
class MemoryStoreConfig:
    """记忆存储配置

    这些默认值作为 fallback 使用，生产环境值通过 global_config.memory 注入。
    """

    sqlite_path: str = "data/memory.db"
    """SQLite 数据库文件路径"""

    qdrant_url: str = ""
    """Qdrant 服务器 URL（空字符串=本地嵌入模式，设置 URL=服务器/云模式）"""

    qdrant_api_key: Optional[str] = field(default=None, repr=False)
    """Qdrant API 密钥（可选，repr=False 避免日志泄露）"""

    qdrant_local_path: str = "data/qdrant"
    """Qdrant 本地模式数据目录"""

    embedding_dimension: int = 1024
    """嵌入向量维度"""

    collection_name_atoms: str = "memory_atoms"
    """记忆原子 Qdrant 集合名称"""

    collection_name_graph: str = "graph_entries"
    """图条目 Qdrant 集合名称"""

    vector_batch_size: int = 100
    """向量批量写入大小"""

    def __repr__(self) -> str:
        """返回配置字符串（隐藏敏感字段）"""
        masked_key = "***" if self.qdrant_api_key else None
        return (
            f"MemoryStoreConfig(sqlite_path={self.sqlite_path!r}, "
            f"qdrant_url={self.qdrant_url!r}, "
            f"qdrant_api_key={masked_key}, "
            f"qdrant_local_path={self.qdrant_local_path!r}, "
            f"embedding_dimension={self.embedding_dimension}, "
            f"collection_name_atoms={self.collection_name_atoms!r}, "
            f"vector_batch_size={self.vector_batch_size})"
        )


# ---------------------------------------------------------------------------
# Qdrant 管理器
# ---------------------------------------------------------------------------


class QdrantManager:
    """Qdrant 向量索引管理器

    封装 Qdrant 集合管理、向量写入/检索/删除操作。
    当 qdrant-client 未安装时静默降级，所有方法返回空结果。
    """

    def __init__(self, config: MemoryStoreConfig):
        self.config = config
        self._client: Optional[Any] = None
        self._available = QDRANT_AVAILABLE

        if not self._available:
            logger.warning("qdrant-client 未安装，向量索引功能不可用。pip install qdrant-client")

    @staticmethod
    def _normalize_point_id(point_id: str | int) -> str | int:
        """将业务 ID 转成 Qdrant 可接受的 point id。

        Qdrant 只接受 UUID 字符串或无符号整数。默认生成的记忆 atom_id 已是 UUID，
        这里保持原值以兼容已有索引；非 UUID 字符串使用 uuid5 做稳定映射。
        """
        if isinstance(point_id, int):
            if 0 <= point_id <= 2**64 - 1:
                return point_id
            point_id = str(point_id)

        value = str(point_id)
        try:
            return str(uuid.UUID(value))
        except (TypeError, ValueError):
            pass

        if value.isdecimal():
            try:
                numeric_id = int(value)
                if str(numeric_id) == value:
                    return numeric_id
            except ValueError:
                pass

        return str(uuid.uuid5(_QDRANT_POINT_NAMESPACE, value))

    @staticmethod
    def _payload_field_names(payload_schema: list[PayloadSchemaField]) -> set[str]:
        return {field["name"] for field in payload_schema}

    @staticmethod
    def _build_filter(
        filters: Optional[dict[str, Any]],
        payload_schema: list[PayloadSchemaField],
    ) -> Any:
        """构建 Qdrant payload filter，忽略非 payload 控制字段。"""
        if not filters or qdrant_models is None:
            return None

        allowed_fields = QdrantManager._payload_field_names(payload_schema)
        conditions = []
        for key, value in filters.items():
            if key not in allowed_fields or value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                values = list(value)
                if not values:
                    continue
                conditions.append(
                    qdrant_models.FieldCondition(
                        key=key,
                        match=qdrant_models.MatchAny(any=values),
                    )
                )
            else:
                conditions.append(
                    qdrant_models.FieldCondition(
                        key=key,
                        match=qdrant_models.MatchValue(value=value),
                    )
                )

        if not conditions:
            return None
        return qdrant_models.Filter(must=conditions)

    @staticmethod
    def _collection_vector_size(collection_info: Any) -> Optional[int]:
        """读取 Qdrant collection 的未命名向量维度。"""
        config = getattr(collection_info, "config", None)
        params = getattr(config, "params", None)
        vectors = getattr(params, "vectors", None)
        if vectors is None:
            return None
        if isinstance(vectors, dict):
            if "" in vectors:
                return getattr(vectors[""], "size", None)
            return None
        return getattr(vectors, "size", None)

    def _query_points(
        self,
        collection_name: str,
        query_vector: list[float],
        qdrant_filter: Any = None,
        limit: int = 10,
    ) -> list[Any]:
        """兼容新旧 qdrant-client 的向量查询 API。"""
        if self._client is None:
            return []
        if hasattr(self._client, "search"):
            return self._client.search(
                collection_name=collection_name,
                query_vector=query_vector,
                query_filter=qdrant_filter,
                limit=limit,
                with_payload=True,
            )

        response = self._client.query_points(
            collection_name=collection_name,
            query=query_vector,
            query_filter=qdrant_filter,
            limit=limit,
            with_payload=True,
        )
        points = getattr(response, "points", response)
        return list(points or [])

    async def initialize(self) -> None:
        """初始化 Qdrant 连接并确保集合存在

        支持两种模式:
        - 服务器/云模式: config.qdrant_url 非空时使用
        - 本地嵌入模式: config.qdrant_url 为空时使用 (无需 Docker)
        """
        if not self._available:
            return

        try:
            if self.config.qdrant_url:
                self._client = _QdrantClient(
                    url=self.config.qdrant_url,
                    api_key=self.config.qdrant_api_key,
                )
                mode = "server"
                source = self.config.qdrant_url
            else:
                self._client = _QdrantClient(
                    path=self.config.qdrant_local_path,
                )
                mode = "local"
                source = self.config.qdrant_local_path

            # 确保集合存在
            await self._ensure_collection(
                self.config.collection_name_atoms,
                self._atoms_payload_schema(),
            )
            await self._ensure_collection(
                self.config.collection_name_graph,
                self._graph_payload_schema(),
            )
            logger.info(
                "Qdrant 已就绪",
                event_code="memory.qdrant.ready",
                mode=mode,
                source=source,
                atom_collection=self.config.collection_name_atoms,
                graph_collection=self.config.collection_name_graph,
            )
        except Exception:
            logger.exception("Qdrant 初始化失败", event_code="memory.qdrant.init_failed")
            self._client = None

    async def close(self) -> None:
        """关闭 Qdrant 连接"""
        self._client = None

    # -- 集合管理 -----------------------------------------------------------

    @staticmethod
    def _atoms_payload_schema() -> list[PayloadSchemaField]:
        """memory_atoms 集合的 payload 字段 schema"""
        return [
            {"name": "atom_id", "type": "keyword"},
            {"name": "atom_type", "type": "keyword"},
            {"name": "user_id", "type": "keyword"},
            {"name": "group_id", "type": "keyword"},
            {"name": "weight", "type": "float"},
            {"name": "importance", "type": "float"},
            {"name": "confidence", "type": "float"},
            {"name": "status", "type": "keyword"},
            {"name": "privacy_level", "type": "keyword"},
            {"name": "source_scene", "type": "keyword"},
            {"name": "source_id", "type": "keyword"},
        ]

    @staticmethod
    def _graph_payload_schema() -> list[PayloadSchemaField]:
        """graph_entries 集合的 payload 字段 schema"""
        return [
            {"name": "entry_id", "type": "keyword"},
            {"name": "subject", "type": "keyword"},
            {"name": "predicate", "type": "keyword"},
            {"name": "object", "type": "keyword"},
            {"name": "confidence", "type": "float"},
        ]

    async def _ensure_collection(self, collection_name: str, payload_schema: list[PayloadSchemaField]) -> None:
        """确保集合存在，不存在则创建"""
        if not self._available or not self._client:
            return

        try:
            collections = self._client.get_collections().collections
            exists = any(c.name == collection_name for c in collections)
        except Exception:
            exists = False

        if exists:
            collection_info = self._client.get_collection(collection_name=collection_name)
            vector_size = self._collection_vector_size(collection_info)
            if vector_size is None:
                raise RuntimeError(
                    f"Qdrant collection '{collection_name}' vector configuration is incompatible with unnamed vectors"
                )
            if vector_size != self.config.embedding_dimension:
                raise RuntimeError(
                    f"Qdrant collection '{collection_name}' vector size {vector_size} "
                    f"!= configured embedding_dimension {self.config.embedding_dimension}"
                )
            return

        if not exists:
            try:
                self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=qdrant_models.VectorParams(
                        size=self.config.embedding_dimension,
                        distance=qdrant_models.Distance.COSINE,
                    ),
                )
                # 创建 payload 索引
                for field_schema in payload_schema:
                    self._client.create_payload_index(
                        collection_name=collection_name,
                        field_name=field_schema["name"],
                        field_type=field_schema["type"],
                    )
                logger.info(
                    "Qdrant 集合已创建", event_code="memory.qdrant.collection_created", collection=collection_name
                )
            except Exception:
                logger.exception(
                    "Qdrant 集合创建失败",
                    event_code="memory.qdrant.collection_create_failed",
                    collection=collection_name,
                )

    # -- 向量写入 -----------------------------------------------------------

    async def upsert_atom_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> bool:
        """写入/更新记忆原子向量"""
        if not self._available:
            return True
        if not self._client:
            return False
        try:
            normalized_payload = dict(payload)
            normalized_payload["atom_id"] = str(point_id)
            self._client.upsert(
                collection_name=self.config.collection_name_atoms,
                points=[
                    qdrant_models.PointStruct(
                        id=self._normalize_point_id(point_id),
                        vector=vector,
                        payload=normalized_payload,
                    )
                ],
            )
            return True
        except Exception:
            logger.exception(
                "Qdrant 原子向量写入失败",
                event_code="memory.qdrant.atom_vector_upsert_failed",
                point_id=point_id,
                vector_dimension=len(vector),
            )
            return False

    async def upsert_graph_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> bool:
        """写入/更新图条目向量"""
        if not self._available:
            return True
        if not self._client:
            return False
        try:
            self._client.upsert(
                collection_name=self.config.collection_name_graph,
                points=[
                    qdrant_models.PointStruct(
                        id=self._normalize_point_id(point_id),
                        vector=vector,
                        payload=payload,
                    )
                ],
            )
            return True
        except Exception:
            logger.exception(
                "Qdrant 图向量写入失败",
                event_code="memory.qdrant.graph_vector_upsert_failed",
                point_id=point_id,
                vector_dimension=len(vector),
            )
            return False

    async def batch_upsert_atom_vectors(
        self,
        points: list[tuple[str, list[float], dict[str, Any]]],
    ) -> int:
        """批量写入记忆原子向量

        Returns:
            int: 成功写入的数量
        """
        if not self._available:
            return len(points)
        if not self._client:
            return 0
        try:
            point_structs = [
                qdrant_models.PointStruct(
                    id=self._normalize_point_id(pid),
                    vector=vec,
                    payload={**pl, "atom_id": str(pid)},
                )
                for pid, vec, pl in points
            ]
            self._client.upsert(
                collection_name=self.config.collection_name_atoms,
                points=point_structs,
            )
            return len(point_structs)
        except Exception:
            logger.exception(
                "Qdrant 原子向量批量写入失败",
                event_code="memory.qdrant.atom_vectors_batch_upsert_failed",
                count=len(points),
            )
            return 0

    # -- 向量检索 -----------------------------------------------------------

    async def search_similar_atoms(
        self,
        query_vector: list[float],
        filters: Optional[dict[str, Any]] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """向量检索相似记忆原子

        Args:
            query_vector: 查询向量
            filters: 过滤条件，如 {"atom_type": "episodic"}
            limit: 返回数量

        Returns:
            list[dict]: 每个元素包含 payload 和 score
        """
        if not self._available or not self._client:
            return []

        try:
            qdrant_filter = self._build_filter(filters, self._atoms_payload_schema())
            results = self._query_points(
                collection_name=self.config.collection_name_atoms,
                query_vector=query_vector,
                qdrant_filter=qdrant_filter,
                limit=limit,
            )
            return [
                {
                    "id": str(hit.id),
                    "score": hit.score,
                    "payload": hit.payload,
                }
                for hit in results
            ]
        except Exception:
            logger.exception(
                "Qdrant 原子向量检索失败",
                event_code="memory.qdrant.atom_vector_search_failed",
                limit=limit,
                has_filters=bool(filters),
            )
            return []

    async def search_similar_graph_entries(
        self,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """向量检索相似图条目"""
        if not self._available or not self._client:
            return []

        try:
            results = self._query_points(
                collection_name=self.config.collection_name_graph,
                query_vector=query_vector,
                limit=limit,
            )
            return [
                {
                    "id": str(hit.id),
                    "score": hit.score,
                    "payload": hit.payload,
                }
                for hit in results
            ]
        except Exception:
            logger.exception(
                "Qdrant 图条目检索失败",
                event_code="memory.qdrant.graph_vector_search_failed",
                limit=limit,
            )
            return []

    async def list_atom_points(self, page_size: int = 256) -> Optional[list[dict[str, Any]]]:
        """分页读取 Qdrant 原子的物理 ID 与可信业务 ID。"""
        if not self._available or not self._client:
            return None

        atom_points: list[dict[str, Any]] = []
        offset: Any = None
        untrusted = 0
        try:
            while True:
                points, next_offset = self._client.scroll(
                    collection_name=self.config.collection_name_atoms,
                    limit=page_size,
                    offset=offset,
                    with_payload=["atom_id"],
                    with_vectors=False,
                )
                for point in points:
                    physical_id = point.id
                    payload_atom_id = (getattr(point, "payload", None) or {}).get("atom_id")
                    business_id: Optional[str] = None
                    if payload_atom_id is not None:
                        candidate = str(payload_atom_id)
                        if self._normalize_point_id(candidate) == self._normalize_point_id(physical_id):
                            business_id = candidate
                    if business_id is None:
                        untrusted += 1
                    atom_points.append({"physical_id": physical_id, "business_id": business_id})

                if next_offset is None:
                    break
                if next_offset == offset:
                    raise RuntimeError("Qdrant scroll offset did not advance")
                offset = next_offset

            if untrusted:
                logger.warning(
                    "Qdrant 原子业务 atom_id 缺失或与物理 ID 不匹配",
                    event_code="memory.qdrant.atom_ids_untrusted_payload",
                    count=untrusted,
                )
            return atom_points
        except Exception:
            logger.exception("Qdrant 原子 point 列表获取失败", event_code="memory.qdrant.atom_points_list_failed")
            return None

    async def list_atom_ids(self, page_size: int = 256) -> Optional[set[str]]:
        """分页读取 Qdrant 中已验证可映射回业务主键的原子 ID。"""
        atom_points = await self.list_atom_points(page_size=page_size)
        if atom_points is None:
            return None
        return {
            point["business_id"]
            for point in atom_points
            if isinstance(point.get("business_id"), str) and point["business_id"]
        }

    # -- 向量删除 -----------------------------------------------------------

    async def delete_atom_vector(self, point_id: str | int) -> bool:
        """删除指定记忆原子的向量"""
        if not self._available:
            return True
        if not self._client:
            return False
        try:
            self._client.delete(
                collection_name=self.config.collection_name_atoms,
                points_selector=qdrant_models.PointIdsList(points=[self._normalize_point_id(point_id)]),
            )
            return True
        except Exception:
            logger.exception(
                "Qdrant 原子向量删除失败",
                event_code="memory.qdrant.atom_vector_delete_failed",
                point_id=point_id,
            )
            return False

    async def set_atom_payload(self, point_id: str, payload: dict[str, Any]) -> bool:
        """更新 Qdrant 中记忆原子的 payload 字段（不改变向量）

        用于权重、状态、置信度等非内容字段的增量更新，
        无需重新生成 embedding。

        Args:
            point_id: 原子 ID
            payload: 要设置/更新的字段字典

        Returns:
            bool: 是否成功
        """
        if not self._available:
            return True
        if not self._client:
            return False
        try:
            self._client.set_payload(
                collection_name=self.config.collection_name_atoms,
                payload=payload,
                points=[self._normalize_point_id(point_id)],
            )
            return True
        except KeyError:
            logger.debug(
                "Qdrant 原子不存在，等待一致性协调",
                event_code="memory.qdrant.atom_payload_missing",
                point_id=point_id,
            )
            return False
        except Exception:
            logger.exception(
                "Qdrant 原子 payload 设置失败",
                event_code="memory.qdrant.atom_payload_set_failed",
                point_id=point_id,
                payload_keys=list(payload.keys()),
            )
            return False

    async def delete_graph_vector(self, entry_id: str) -> bool:
        """删除指定图条目的向量"""
        if not self._available:
            return True
        if not self._client:
            return False
        try:
            self._client.delete(
                collection_name=self.config.collection_name_graph,
                points_selector=qdrant_models.PointIdsList(points=[self._normalize_point_id(entry_id)]),
            )
            return True
        except Exception:
            logger.exception(
                "Qdrant 图向量删除失败",
                event_code="memory.qdrant.graph_vector_delete_failed",
                entry_id=entry_id,
            )
            return False

    # -- 集合管理工具 -------------------------------------------------------

    async def collection_info(self, collection_name: str) -> Optional[dict[str, Any]]:
        """获取集合信息"""
        if not self._available or not self._client:
            return None
        try:
            info = self._client.get_collection(collection_name)
            return {
                "name": collection_name,
                "vectors_count": info.points_count,
                "status": info.status,
            }
        except Exception:
            logger.exception(
                "Qdrant 集合信息获取失败",
                event_code="memory.qdrant.collection_info_failed",
                collection=collection_name,
            )
            return None

    async def delete_collection(self, collection_name: str) -> bool:
        """删除集合"""
        if not self._available or not self._client:
            return False
        try:
            self._client.delete_collection(collection_name)
            logger.info("Qdrant 集合已删除", event_code="memory.qdrant.collection_deleted", collection=collection_name)
            return True
        except Exception:
            logger.exception(
                "Qdrant 集合删除失败",
                event_code="memory.qdrant.collection_delete_failed",
                collection=collection_name,
            )
            return False


# ---------------------------------------------------------------------------
# MemoryStore — 统一记忆存储入口
# ---------------------------------------------------------------------------


class MemoryStore:
    """统一记忆存储入口，封装 SQLite + Qdrant 双层存储

    使用方式:
        store = MemoryStore(config)
        await store.initialize()
        # ...
        store = MemoryStore.get_instance()
    """

    _instance: Optional["MemoryStore"] = None

    def __new__(cls, *args, **kwargs) -> "MemoryStore":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False  # type: ignore
        return cls._instance

    def __init__(self, config: Optional[MemoryStoreConfig] = None):
        if self._initialized:  # type: ignore
            return

        self.config = config or MemoryStoreConfig()
        self.qdrant = QdrantManager(self.config)

    @classmethod
    def get_instance(cls) -> "MemoryStore":
        """获取 MemoryStore 单例实例"""
        if cls._instance is None:
            logger.error("MemoryStore 尚未初始化就被调用", caller="get_instance")
            raise RuntimeError("MemoryStore 未初始化，请先调用 MemoryStore(config)")
        return cls._instance

    async def initialize(self) -> None:
        """异步初始化：确保数据库表存在 + 连接 Qdrant"""
        # 仅当用户显式改了 sqlite_path 时重设 ORM 数据库路径；默认路径保持 schema.py 的绑定，避免破坏测试中的临时 DB 绑定。
        if self.config.sqlite_path != MemoryStoreConfig.sqlite_path:
            configure_memory_database(self.config.sqlite_path)
        # 确保 SQLite 数据库表已创建（从 schema 模块级自动初始化移至此处）
        initialize_database()
        await self.qdrant.initialize()
        self._initialized = True
        logger.info(
            "MemoryStore 初始化完成", event_code="memory.store.initialized", sqlite_path=self.config.sqlite_path
        )

    async def close(self) -> None:
        """关闭存储连接"""
        await self.qdrant.close()
        if not memory_db.is_closed():
            memory_db.close()
        self._initialized = False
        type(self)._instance = None
        logger.info("MemoryStore 已关闭", event_code="memory.store.closed")

    # -- 原子 CRUD ----------------------------------------------------------

    async def insert_atom(self, atom_data: dict[str, Any]) -> str:
        """插入一条记忆原子

        Args:
            atom_data: 原子字段字典（不含 atom_id，自动生成）

        Returns:
            str: 生成的 atom_id
        """
        atom_data = dict(atom_data)
        atom_id = str(atom_data.get("atom_id") or uuid.uuid4())
        atom_data["atom_id"] = atom_id
        _normalize_datetime_fields(atom_data, fill_missing=True)

        # JSON 字段序列化
        if isinstance(atom_data.get("entities"), (list, dict)):
            atom_data["entities"] = json.dumps(atom_data["entities"], ensure_ascii=False)

        try:
            with memory_db.atomic():
                MemoryAtom.create(**atom_data)
        except Exception:
            logger.exception("记忆原子写入失败", event_code="memory.atom.insert_failed", atom_id=atom_id)
            raise

        logger.debug(
            "记忆原子写入完成",
            event_code="memory.atom.inserted",
            atom_id=atom_id,
            atom_type=atom_data.get("atom_type", "unknown"),
        )
        return atom_id

    async def update_atom(self, atom_id: str, updates: dict[str, Any]) -> bool:
        """更新记忆原子

        Args:
            atom_id: 原子 ID
            updates: 要更新的字段字典

        Returns:
            bool: 是否成功
        """
        updates = dict(updates)
        _normalize_datetime_fields(updates)

        # JSON 字段序列化
        if isinstance(updates.get("entities"), (list, dict)):
            updates["entities"] = json.dumps(updates["entities"], ensure_ascii=False)

        try:
            with memory_db:
                query = MemoryAtom.update(**updates).where(MemoryAtom.atom_id == atom_id)
                rows = query.execute()
            if rows > 0:
                logger.debug("记忆原子更新完成", event_code="memory.atom.updated", atom_id=atom_id, rows=rows)
            return rows > 0
        except Exception:
            logger.exception("记忆原子更新失败", event_code="memory.atom.update_failed", atom_id=atom_id)
            return False

    async def update_atoms_batch(
        self,
        updates_list: list[tuple[str, dict[str, Any]]],
    ) -> int:
        """批量更新记忆原子（单事务）

        在单个事务中执行所有更新，将 N 次独立事务压缩为 1 次。
        每个更新仍为独立 SQL UPDATE，但共享同一个数据库事务。

        Args:
            updates_list: [(atom_id, updates_dict), ...]

        Returns:
            int: 成功更新的行数
        """
        if not updates_list:
            return 0
        count = 0
        try:
            with memory_db.atomic():
                for atom_id, updates in updates_list:
                    normalized_updates = dict(updates)
                    _normalize_datetime_fields(normalized_updates)
                    if isinstance(normalized_updates.get("entities"), (list, dict)):
                        normalized_updates["entities"] = json.dumps(normalized_updates["entities"], ensure_ascii=False)
                    query = MemoryAtom.update(**normalized_updates).where(MemoryAtom.atom_id == atom_id)
                    count += query.execute()
            return count
        except Exception:
            logger.exception(
                "记忆原子批量更新失败", event_code="memory.atom.batch_update_failed", count=len(updates_list)
            )
            return 0

    async def delete_atom(self, atom_id: str) -> bool:
        """删除记忆原子及其向量索引

        Args:
            atom_id: 原子 ID

        Returns:
            bool: 是否成功
        """
        try:
            with memory_db.atomic():
                EpisodicDetail.delete().where(EpisodicDetail.atom == atom_id).execute()
                SemanticDetail.delete().where(SemanticDetail.atom == atom_id).execute()
                MemoryTraceChain.delete().where(MemoryTraceChain.atom_id == atom_id).execute()
                ConflictObservation.delete().where(
                    (ConflictObservation.atom_a_id == atom_id) | (ConflictObservation.atom_b_id == atom_id)
                ).execute()
                AtomAssociationModel.delete().where(
                    (AtomAssociationModel.atom_a_id == atom_id) | (AtomAssociationModel.atom_b_id == atom_id)
                ).execute()
                query = MemoryAtom.delete().where(MemoryAtom.atom_id == atom_id)
                rows = query.execute()
            if rows > 0:
                await self.qdrant.delete_atom_vector(atom_id)
                logger.debug("记忆原子已删除", event_code="memory.atom.deleted", atom_id=atom_id)
            return rows > 0
        except Exception:
            logger.exception("记忆原子删除失败", event_code="memory.atom.delete_failed", atom_id=atom_id)
            return False

    async def archive_atom(self, atom_id: str) -> bool:
        """归档记忆原子并从向量索引中移除。"""
        try:
            atom = MemoryAtom.get_or_none(MemoryAtom.atom_id == atom_id)
            if atom is None:
                logger.warning(
                    "记忆原子归档失败，原子不存在", event_code="memory.atom.archive_missing", atom_id=atom_id
                )
                return False

            metadata: dict[str, Any] = {
                "atom_id": atom.atom_id,
                "atom_type": atom.atom_type,
                "importance": atom.importance,
                "confidence": atom.confidence,
                "weight": atom.weight,
                "source_scene": atom.source_scene,
                "source_id": atom.source_id,
                "privacy_level": atom.privacy_level,
                "reinforcement_count": atom.reinforcement_count,
                "ttl_days": atom.ttl_days,
                "decay_type": atom.decay_type,
                "trace_chain_id": atom.trace_chain_id,
                "embedding_id": atom.embedding_id,
            }
            timestamp = atom.created_at.timestamp() if atom.created_at else datetime.datetime.now().timestamp()

            with memory_db.atomic():
                RawMessageArchive.create(
                    stream_id=f"memory_archive_{atom.source_scene or 'unknown'}",
                    message_id=atom.atom_id,
                    user_id="system",
                    content=json.dumps(
                        {"content": atom.content, "metadata": metadata},
                        ensure_ascii=False,
                    ),
                    timestamp=timestamp,
                    chat_type=f"memory_archive_{atom.atom_type or 'unknown'}",
                )
                rows = MemoryAtom.update(status="archived").where(MemoryAtom.atom_id == atom_id).execute()

            if rows > 0:
                await self.qdrant.delete_atom_vector(atom_id)
                logger.debug("记忆原子已归档", event_code="memory.atom.archived", atom_id=atom_id)
            return rows > 0
        except Exception:
            logger.exception("记忆原子归档失败", event_code="memory.atom.archive_failed", atom_id=atom_id)
            return False

    async def migrate_atom(self, atom_id: str, target_type: str) -> bool:
        """迁移记忆原子的类型，并同步 Qdrant payload。"""
        if not target_type:
            logger.warning(
                "记忆原子迁移失败，目标类型为空", event_code="memory.atom.migrate_empty_target", atom_id=atom_id
            )
            return False

        try:
            rows = MemoryAtom.update(atom_type=target_type).where(MemoryAtom.atom_id == atom_id).execute()
            if rows > 0:
                await self.qdrant.set_atom_payload(atom_id, {"atom_type": target_type})
                logger.debug(
                    "记忆原子类型已迁移", event_code="memory.atom.migrated", atom_id=atom_id, target_type=target_type
                )
            return rows > 0
        except Exception:
            logger.exception(
                "记忆原子迁移失败",
                event_code="memory.atom.migrate_failed",
                atom_id=atom_id,
                target_type=target_type,
            )
            return False

    async def get_atom(self, atom_id: str) -> Optional[dict[str, Any]]:
        """获取单条记忆原子

        Args:
            atom_id: 原子 ID

        Returns:
            Optional[dict]: 原子数据，不存在时返回 None
        """
        try:
            atom = MemoryAtom.get_or_none(MemoryAtom.atom_id == atom_id)
            if atom is None:
                return None
            return self._atom_to_dict(atom)
        except Exception:
            logger.exception("记忆原子获取失败", event_code="memory.atom.get_failed", atom_id=atom_id)
            return None

    async def get_atoms_batch(self, atom_ids: list[str]) -> dict[str, dict[str, Any]]:
        """批量获取记忆原子（单查询）

        使用 SELECT ... WHERE atom_id IN (...) 一次加载所有原子，
        将 N 次独立查询压缩为 1 次。

        Args:
            atom_ids: 原子 ID 列表

        Returns:
            dict[str, dict]: {atom_id: atom_data_dict} 映射，不存在的 ID 不包含在结果中
        """
        if not atom_ids:
            return {}
        try:
            atoms = MemoryAtom.select().where(MemoryAtom.atom_id.in_(atom_ids))
            return {atom.atom_id: self._atom_to_dict(atom) for atom in atoms}
        except Exception:
            logger.exception("记忆原子批量获取失败", event_code="memory.atom.batch_get_failed", count=len(atom_ids))
            return {}

    async def list_atom_ids(self, status: Optional[str] = None) -> Optional[set[str]]:
        """读取 SQLite 中的记忆原子 ID；查询失败时返回 ``None``。"""
        try:
            with memory_db:
                query = MemoryAtom.select(MemoryAtom.atom_id)
                if status:
                    query = query.where(MemoryAtom.status == status)
                return {str(atom.atom_id) for atom in query}
        except Exception:
            logger.exception(
                "记忆原子 ID 列表获取失败",
                event_code="memory.atom.ids_list_failed",
                status=status,
            )
            return None

    async def list_atoms(
        self,
        atom_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """列出记忆原子

        Args:
            atom_type: 按类型过滤
            status: 按状态过滤
            limit: 返回数量上限
            offset: 偏移量

        Returns:
            list[dict]: 原子数据列表
        """
        try:
            conditions = []
            if atom_type:
                conditions.append(MemoryAtom.atom_type == atom_type)
            if status:
                conditions.append(MemoryAtom.status == status)

            with memory_db:
                if conditions:
                    query = MemoryAtom.select().where(*conditions)
                else:
                    query = MemoryAtom.select()
                query = query.order_by(MemoryAtom.created_at.desc()).limit(limit).offset(offset)
                return [self._atom_to_dict(a) for a in query]
        except Exception:
            logger.exception(
                "记忆原子列表获取失败",
                event_code="memory.atom.list_failed",
                atom_type=atom_type,
                status=status,
                limit=limit,
                offset=offset,
            )
            return []

    # -- 向量检索 -----------------------------------------------------------

    async def search_similar(
        self,
        query_vector: list[float],
        filters: Optional[dict[str, Any]] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """向量检索相似记忆原子

        Args:
            query_vector: 查询向量
            filters: Qdrant 过滤条件
            limit: 返回数量

        Returns:
            list[dict]: 检索结果，含 payload 和 score
        """
        results = await self.qdrant.search_similar_atoms(query_vector, filters, limit)
        logger.debug(
            "记忆向量搜索完成",
            event_code="memory.vector_search.completed",
            query_len=len(query_vector),
            results_count=len(results),
            limit=limit,
            has_filters=bool(filters),
        )
        if not results:
            logger.debug(
                "记忆向量搜索结果为空",
                event_code="memory.vector_search.empty",
                query_len=len(query_vector),
                limit=limit,
            )
        return results

    # -- Qdrant 重建 --------------------------------------------------------

    async def rebuild_qdrant_index(self) -> int:
        """从 SQLite 全量重建 Qdrant 索引

        Returns:
            int: 重建的向量数量
        """
        logger.warning(
            "Qdrant 索引重建暂不可用：SQLite 未保存原始向量，不能仅凭 embedding_id 重建",
            event_code="memory.qdrant.index_rebuild_unavailable",
        )
        return 0

    # -- 统计信息 -----------------------------------------------------------

    async def get_statistics(self) -> dict[str, Any]:
        """获取记忆存储统计信息"""
        try:
            with memory_db:
                total_atoms = MemoryAtom.select().count()
                active_atoms = MemoryAtom.select().where(MemoryAtom.status == "active").count()
                type_distribution = {}
                for atom_type in ["episodic", "factual", "relational", "preference", "planned"]:
                    count = MemoryAtom.select().where(MemoryAtom.atom_type == atom_type).count()
                    if count > 0:
                        type_distribution[atom_type] = count

            qdrant_info = await self.qdrant.collection_info(self.config.collection_name_atoms)

            return {
                "total_atoms": total_atoms,
                "active_atoms": active_atoms,
                "type_distribution": type_distribution,
                "qdrant_available": QDRANT_AVAILABLE and self.qdrant._client is not None,
                "qdrant_atoms_collection": qdrant_info,
            }
        except Exception as e:
            logger.exception("记忆存储统计信息获取失败", event_code="memory.store.stats_failed")
            return {"error": str(e)}

    # -- 内部工具 -----------------------------------------------------------

    @staticmethod
    def _atom_to_dict(atom: MemoryAtom) -> dict[str, Any]:
        """将 MemoryAtom Peewee 实例转为字典"""
        data = {
            "atom_id": atom.atom_id,
            "atom_type": atom.atom_type,
            "content": atom.content,
            "importance": atom.importance,
            "confidence": atom.confidence,
            "weight": atom.weight,
            "created_at": atom.created_at.isoformat() if atom.created_at else None,
            "last_accessed_at": atom.last_accessed_at.isoformat() if atom.last_accessed_at else None,
            "last_reinforced_at": atom.last_reinforced_at.isoformat() if atom.last_reinforced_at else None,
            "ttl_days": atom.ttl_days,
            "decay_type": atom.decay_type,
            "reinforcement_count": atom.reinforcement_count,
            "source_scene": atom.source_scene,
            "source_id": atom.source_id,
            "privacy_level": atom.privacy_level,
            "status": atom.status,
            "trace_chain_id": atom.trace_chain_id,
            "embedding_id": atom.embedding_id,
        }
        # 反序列化 JSON 字段
        if atom.entities:
            try:
                data["entities"] = json.loads(atom.entities)
            except (json.JSONDecodeError, TypeError):
                data["entities"] = atom.entities
        return data
