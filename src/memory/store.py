"""记忆存储层 — MemoryStore 统一封装 + Qdrant 向量索引管理

提供 SQLite (源数据) + Qdrant (向量索引) 双层存储的统一入口。
"""

import datetime
import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from src.common.logger import get_logger
from src.memory.schema import MemoryAtom, memory_db

logger = get_logger("memory.store")

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
    """记忆存储配置"""

    sqlite_path: str = "data/memory.db"
    qdrant_url: str = ""  # 空字符串=本地嵌入模式，设置 URL=服务器/云模式
    qdrant_api_key: Optional[str] = None
    qdrant_local_path: str = "data/qdrant"  # 本地模式数据目录
    embedding_dimension: int = 1024
    collection_name_atoms: str = "memory_atoms"
    collection_name_graph: str = "graph_entries"
    vector_batch_size: int = 100


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
                f"Qdrant [{mode}] 已就绪: {source}, "
                f"集合: {self.config.collection_name_atoms}, {self.config.collection_name_graph}"
            )
        except Exception as e:
            logger.error(f"Qdrant 初始化失败: {e}")
            self._client = None

    async def close(self) -> None:
        """关闭 Qdrant 连接"""
        self._client = None

    # -- 集合管理 -----------------------------------------------------------

    @staticmethod
    def _atoms_payload_schema() -> list[dict]:
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
        ]

    @staticmethod
    def _graph_payload_schema() -> list[dict]:
        """graph_entries 集合的 payload 字段 schema"""
        return [
            {"name": "entry_id", "type": "keyword"},
            {"name": "subject", "type": "keyword"},
            {"name": "predicate", "type": "keyword"},
            {"name": "object", "type": "keyword"},
            {"name": "confidence", "type": "float"},
        ]

    async def _ensure_collection(self, collection_name: str, payload_schema: list[dict]) -> None:
        """确保集合存在，不存在则创建"""
        if not self._available or not self._client:
            return

        try:
            collections = self._client.get_collections().collections
            exists = any(c.name == collection_name for c in collections)
        except Exception:
            exists = False

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
                logger.info(f"Qdrant 集合 '{collection_name}' 已创建")
            except Exception as e:
                logger.error(f"创建 Qdrant 集合 '{collection_name}' 失败: {e}")

    # -- 向量写入 -----------------------------------------------------------

    async def upsert_atom_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> bool:
        """写入/更新记忆原子向量"""
        if not self._available or not self._client:
            return False
        try:
            self._client.upsert(
                collection_name=self.config.collection_name_atoms,
                points=[
                    qdrant_models.PointStruct(
                        id=hash(point_id) % (2**63),
                        vector=vector,
                        payload=payload,
                    )
                ],
            )
            return True
        except Exception as e:
            logger.error(f"Qdrant upsert 原子向量失败 ({point_id}): {e}")
            return False

    async def upsert_graph_vector(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> bool:
        """写入/更新图条目向量"""
        if not self._available or not self._client:
            return False
        try:
            self._client.upsert(
                collection_name=self.config.collection_name_graph,
                points=[
                    qdrant_models.PointStruct(
                        id=hash(point_id) % (2**63),
                        vector=vector,
                        payload=payload,
                    )
                ],
            )
            return True
        except Exception as e:
            logger.error(f"Qdrant upsert 图向量失败 ({point_id}): {e}")
            return False

    async def batch_upsert_atom_vectors(
        self,
        points: list[tuple[str, list[float], dict[str, Any]]],
    ) -> int:
        """批量写入记忆原子向量

        Returns:
            int: 成功写入的数量
        """
        if not self._available or not self._client:
            return 0
        try:
            point_structs = [
                qdrant_models.PointStruct(
                    id=hash(pid) % (2**63),
                    vector=vec,
                    payload=pl,
                )
                for pid, vec, pl in points
            ]
            self._client.upsert(
                collection_name=self.config.collection_name_atoms,
                points=point_structs,
            )
            return len(point_structs)
        except Exception as e:
            logger.error(f"Qdrant 批量写入原子向量失败: {e}")
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
            qdrant_filter = None
            if filters:
                conditions = []
                for key, value in filters.items():
                    conditions.append(
                        qdrant_models.FieldCondition(
                            key=key,
                            match=qdrant_models.MatchValue(value=value),
                        )
                    )
                qdrant_filter = qdrant_models.Filter(must=conditions)

            results = self._client.search(
                collection_name=self.config.collection_name_atoms,
                query_vector=query_vector,
                query_filter=qdrant_filter,
                limit=limit,
                with_payload=True,
            )
            return [
                {
                    "id": str(hit.id),
                    "score": hit.score,
                    "payload": hit.payload,
                }
                for hit in results
            ]
        except Exception as e:
            logger.error(f"Qdrant 向量检索失败: {e}")
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
            results = self._client.search(
                collection_name=self.config.collection_name_graph,
                query_vector=query_vector,
                limit=limit,
                with_payload=True,
            )
            return [
                {
                    "id": str(hit.id),
                    "score": hit.score,
                    "payload": hit.payload,
                }
                for hit in results
            ]
        except Exception as e:
            logger.error(f"Qdrant 图条目检索失败: {e}")
            return []

    # -- 向量删除 -----------------------------------------------------------

    async def delete_atom_vector(self, point_id: str) -> bool:
        """删除指定记忆原子的向量"""
        if not self._available or not self._client:
            return False
        try:
            self._client.delete(
                collection_name=self.config.collection_name_atoms,
                points_selector=qdrant_models.PointIdsList(points=[hash(point_id) % (2**63)]),
            )
            return True
        except Exception as e:
            logger.error(f"Qdrant 删除原子向量失败 ({point_id}): {e}")
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
        if not self._available or not self._client:
            return False
        try:
            self._client.set_payload(
                collection_name=self.config.collection_name_atoms,
                payload=payload,
                points=[hash(point_id) % (2**63)],
            )
            return True
        except Exception as e:
            logger.error(f"Qdrant 设置原子 payload 失败 ({point_id}): {e}")
            return False

    async def delete_graph_vector(self, entry_id: str) -> bool:
        """删除指定图条目的向量"""
        if not self._available or not self._client:
            return False
        try:
            self._client.delete(
                collection_name=self.config.collection_name_graph,
                points_selector=qdrant_models.PointIdsList(points=[hash(entry_id) % (2**63)]),
            )
            return True
        except Exception as e:
            logger.error(f"Qdrant 删除图向量失败 ({entry_id}): {e}")
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
        except Exception as e:
            logger.error(f"获取集合信息失败: {e}")
            return None

    async def delete_collection(self, collection_name: str) -> bool:
        """删除集合"""
        if not self._available or not self._client:
            return False
        try:
            self._client.delete_collection(collection_name)
            logger.info(f"Qdrant 集合 '{collection_name}' 已删除")
            return True
        except Exception as e:
            logger.error(f"删除集合失败: {e}")
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
        """异步初始化：连接 Qdrant"""
        await self.qdrant.initialize()
        logger.info("MemoryStore 初始化完成")

    async def close(self) -> None:
        """关闭存储连接"""
        await self.qdrant.close()
        if not memory_db.is_closed():
            memory_db.close()
        logger.info("MemoryStore 已关闭")

    # -- 原子 CRUD ----------------------------------------------------------

    async def insert_atom(self, atom_data: dict[str, Any]) -> str:
        """插入一条记忆原子

        Args:
            atom_data: 原子字段字典（不含 atom_id，自动生成）

        Returns:
            str: 生成的 atom_id
        """
        atom_id = str(uuid.uuid4())
        atom_data.setdefault("atom_id", atom_id)
        atom_data.setdefault("created_at", datetime.datetime.now())
        atom_data.setdefault("last_accessed_at", datetime.datetime.now())
        atom_data.setdefault("last_reinforced_at", datetime.datetime.now())

        # JSON 字段序列化
        if isinstance(atom_data.get("entities"), (list, dict)):
            atom_data["entities"] = json.dumps(atom_data["entities"], ensure_ascii=False)

        try:
            with memory_db:
                MemoryAtom.create(**atom_data)
        except Exception as e:
            logger.error(f"原子写入失败: {e}", atom_id=atom_id, exc_info=True)
            raise

        logger.debug("原子写入成功", atom_id=atom_id)
        logger.debug(f"记忆原子已写入: {atom_id} ({atom_data.get('atom_type', 'unknown')})")
        return atom_id

    async def update_atom(self, atom_id: str, updates: dict[str, Any]) -> bool:
        """更新记忆原子

        Args:
            atom_id: 原子 ID
            updates: 要更新的字段字典

        Returns:
            bool: 是否成功
        """
        # JSON 字段序列化
        if isinstance(updates.get("entities"), (list, dict)):
            updates["entities"] = json.dumps(updates["entities"], ensure_ascii=False)

        try:
            with memory_db:
                query = MemoryAtom.update(**updates).where(MemoryAtom.atom_id == atom_id)
                rows = query.execute()
            if rows > 0:
                logger.debug("原子更新成功", atom_id=atom_id)
            return rows > 0
        except Exception as e:
            logger.error(f"更新记忆原子失败 ({atom_id}): {e}")
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
                    if isinstance(updates.get("entities"), (list, dict)):
                        updates["entities"] = json.dumps(updates["entities"], ensure_ascii=False)
                    query = MemoryAtom.update(**updates).where(MemoryAtom.atom_id == atom_id)
                    count += query.execute()
            return count
        except Exception as e:
            logger.error(f"批量更新记忆原子失败: {e}")
            return 0

    async def delete_atom(self, atom_id: str) -> bool:
        """删除记忆原子及其向量索引

        Args:
            atom_id: 原子 ID

        Returns:
            bool: 是否成功
        """
        try:
            with memory_db:
                query = MemoryAtom.delete().where(MemoryAtom.atom_id == atom_id)
                rows = query.execute()
            if rows > 0:
                await self.qdrant.delete_atom_vector(atom_id)
                logger.debug(f"记忆原子已删除: {atom_id}")
            return rows > 0
        except Exception as e:
            logger.error(f"删除记忆原子失败 ({atom_id}): {e}")
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
        except Exception as e:
            logger.error(f"获取记忆原子失败 ({atom_id}): {e}")
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
        except Exception as e:
            logger.error(f"批量获取记忆原子失败: {e}")
            return {}

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
        except Exception as e:
            logger.error(f"列出记忆原子失败: {e}")
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
        logger.debug("向量搜索完成", query_len=len(query_vector), results_count=len(results))
        if not results:
            logger.debug("向量搜索结果为空", query_len=len(query_vector))
        return results

    # -- Qdrant 重建 --------------------------------------------------------

    async def rebuild_qdrant_index(self) -> int:
        """从 SQLite 全量重建 Qdrant 索引

        Returns:
            int: 重建的向量数量
        """
        if not QDRANT_AVAILABLE:
            logger.warning("qdrant-client 未安装，无法重建索引")
            return 0

        count = 0
        try:
            with memory_db:
                atoms = MemoryAtom.select().where(MemoryAtom.status == "active")
                for atom in atoms:
                    # embedding_id 为空时跳过（未生成嵌入向量）
                    if not atom.embedding_id:
                        continue
                    # 注意：这里需要外部提供 vector，无法凭空重建
                    # 此方法仅为框架，实际重建需要调用 embedding 模型
                    count += 1
            logger.info(f"Qdrant 索引重建完成，共 {count} 条（需补充向量数据）")
            return count
        except Exception as e:
            logger.error(f"Qdrant 索引重建失败: {e}")
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
            logger.error(f"获取统计信息失败: {e}")
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
