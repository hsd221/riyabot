"""图记忆存储层 — GraphNode / GraphEdge / GraphEntry 的 CRUD 封装

提供图记忆结构的增删查改操作，供 DreamAgent 等组件对记忆进行实体提取、
关系链接和三元组存储。
"""

import json
from typing import Any, Optional

from src.common.logger import get_logger
from src.memory.schema import GraphEdge, GraphEntry, GraphNode, memory_db

logger = get_logger("memory.graph")


class GraphStore:
    """图谱存储 CRUD 封装

    管理三种图元素：
    - GraphNode：记忆节点（实体、概念、事件等）
    - GraphEdge：节点间关系边
    - GraphEntry：SPO 三元组条目

    所有操作复用 memory_db 的数据库连接和 WAL 事务模式。
    """

    def __init__(self) -> None:
        self.db = memory_db
        # 自动建表（幂等）
        with self.db:
            self.db.create_tables([GraphNode, GraphEdge, GraphEntry], safe=True)

    # ------------------------------------------------------------------
    # Node 操作
    # ------------------------------------------------------------------

    def add_node(
        self,
        node_type: str,
        label: str,
        properties: Optional[dict[str, Any]] = None,
    ) -> int:
        """创建图节点，返回 node_id

        Args:
            node_type: 节点类型（如 "person", "concept", "event"）
            label: 节点标签（唯一标识）
            properties: 可选附加属性字典，自动序列化为 JSON

        Returns:
            int: 新创建节点的 id
        """
        props_json = json.dumps(properties, ensure_ascii=False) if properties else None
        try:
            with self.db:
                node = GraphNode.create(
                    node_type=node_type,
                    label=label,
                    properties=props_json,
                )
            logger.debug("图节点已创建", node_id=node.id, node_type=node_type, label=label)
            return node.id
        except Exception as e:
            logger.error(
                f"创建图节点失败: {e}",
                node_type=node_type,
                label=label,
                exc_info=True,
            )
            raise

    def find_or_create_node(self, node_type: str, label: str) -> int:
        """查找已有节点，不存在则创建。返回 node_id

        Args:
            node_type: 节点类型
            label: 节点标签

        Returns:
            int: 节点 id（已有或新建）
        """
        try:
            with self.db:
                node, created = GraphNode.get_or_create(
                    node_type=node_type,
                    label=label,
                )
            if created:
                logger.debug("图节点已新建", node_id=node.id, label=label)
            else:
                logger.debug("图节点已存在", node_id=node.id, label=label)
            return node.id
        except Exception as e:
            logger.error(
                f"查找/创建图节点失败: {e}",
                node_type=node_type,
                label=label,
                exc_info=True,
            )
            raise

    def get_node(self, node_id: int) -> Optional[dict[str, Any]]:
        """按 id 获取节点

        Args:
            node_id: 节点 ID

        Returns:
            Optional[dict]: 节点数据字典，不存在时返回 None
        """
        try:
            node = GraphNode.get_or_none(GraphNode.id == node_id)
            if node is None:
                return None
            return self._node_to_dict(node)
        except Exception as e:
            logger.error(f"获取图节点失败 (id={node_id}): {e}", exc_info=True)
            raise

    def search_nodes(
        self,
        label_pattern: str,
        node_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """按 label LIKE 模式搜索节点

        Args:
            label_pattern: SQL LIKE 模式（如 "%量子%"）
            node_type: 可选类型过滤

        Returns:
            list[dict]: 匹配的节点字典列表
        """
        try:
            conditions = [GraphNode.label**label_pattern]
            if node_type:
                conditions.append(GraphNode.node_type == node_type)

            with self.db:
                query = GraphNode.select().where(*conditions)
                return [self._node_to_dict(n) for n in query]
        except Exception as e:
            logger.error(
                f"搜索图节点失败: {e}",
                label_pattern=label_pattern,
                node_type=node_type,
                exc_info=True,
            )
            return []

    def delete_node(self, node_id: int) -> bool:
        """删除节点及其关联的所有边

        Args:
            node_id: 节点 ID

        Returns:
            bool: 是否删除了节点
        """
        try:
            with self.db.atomic():
                # 先删除关联边
                GraphEdge.delete().where(
                    (GraphEdge.source_node_id == str(node_id)) | (GraphEdge.target_node_id == str(node_id))
                ).execute()
                # 再删除节点
                rows = GraphNode.delete().where(GraphNode.id == node_id).execute()
            if rows > 0:
                logger.debug("图节点已删除", node_id=node_id)
            return rows > 0
        except Exception as e:
            logger.error(f"删除图节点失败 (id={node_id}): {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Edge 操作
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source_node_id: int,
        target_node_id: int,
        predicate: str,
        confidence: float = 0.5,
    ) -> int:
        """创建图边，返回 edge_id

        Args:
            source_node_id: 源节点 ID
            target_node_id: 目标节点 ID
            predicate: 关系谓词（如 "related_to", "contradicts"）
            confidence: 置信度（0.0 ~ 1.0）

        Returns:
            int: 新创建边的 id
        """
        try:
            with self.db:
                edge = GraphEdge.create(
                    source_node_id=str(source_node_id),
                    target_node_id=str(target_node_id),
                    predicate=predicate,
                    confidence=confidence,
                )
            logger.debug(
                "图边已创建",
                edge_id=edge.id,
                predicate=predicate,
                source=source_node_id,
                target=target_node_id,
            )
            return edge.id
        except Exception as e:
            logger.error(
                f"创建图边失败: {e}",
                source=source_node_id,
                target=target_node_id,
                predicate=predicate,
                exc_info=True,
            )
            raise

    def get_edges_for_node(self, node_id: int) -> list[dict[str, Any]]:
        """获取节点所有关联边（双向）

        Args:
            node_id: 节点 ID

        Returns:
            list[dict]: 边字典列表，每个包含 source_node_id / target_node_id / predicate / confidence
        """
        sid, tid = str(node_id), str(node_id)
        try:
            with self.db:
                query = GraphEdge.select().where((GraphEdge.source_node_id == sid) | (GraphEdge.target_node_id == tid))
                return [self._edge_to_dict(e) for e in query]
        except Exception as e:
            logger.error(f"获取节点关联边失败 (node_id={node_id}): {e}", exc_info=True)
            return []

    def edge_exists(
        self,
        source_node_id: int,
        target_node_id: int,
        predicate: str,
    ) -> bool:
        """检查同向同谓词边是否已存在

        Args:
            source_node_id: 源节点 ID
            target_node_id: 目标节点 ID
            predicate: 关系谓词

        Returns:
            bool: 是否存在完全匹配的边
        """
        try:
            with self.db:
                count = (
                    GraphEdge.select()
                    .where(
                        GraphEdge.source_node_id == str(source_node_id),
                        GraphEdge.target_node_id == str(target_node_id),
                        GraphEdge.predicate == predicate,
                    )
                    .count()
                )
                return count > 0
        except Exception as e:
            logger.error(
                f"检查图边存在性失败: {e}",
                source=source_node_id,
                target=target_node_id,
                predicate=predicate,
                exc_info=True,
            )
            return False

    def delete_edge(self, edge_id: int) -> bool:
        """删除指定边

        Args:
            edge_id: 边 ID

        Returns:
            bool: 是否成功删除
        """
        try:
            with self.db:
                rows = GraphEdge.delete().where(GraphEdge.id == edge_id).execute()
            return rows > 0
        except Exception as e:
            logger.error(f"删除图边失败 (edge_id={edge_id}): {e}", exc_info=True)
            return False

    def link_atoms(
        self,
        source_label: str,
        source_type: str,
        target_label: str,
        target_type: str,
        predicate: str,
        confidence: float = 0.5,
    ) -> tuple[int, int]:
        """高层方法：查找/创建两个节点并用边连接

        自动执行 find_or_create 避免重复节点，若边已存在则跳过创建。

        Args:
            source_label: 源节点标签
            source_type: 源节点类型
            target_label: 目标节点标签
            target_type: 目标节点类型
            predicate: 关系谓词
            confidence: 置信度

        Returns:
            tuple[int, int]: (source_node_id, target_node_id)
        """
        try:
            src_id = self.find_or_create_node(source_type, source_label)
            tgt_id = self.find_or_create_node(target_type, target_label)

            if not self.edge_exists(src_id, tgt_id, predicate):
                self.add_edge(src_id, tgt_id, predicate, confidence)
                logger.debug(
                    "原子链接完成",
                    source=source_label,
                    target=target_label,
                    predicate=predicate,
                )
            else:
                logger.debug(
                    "原子连接已存在，跳过",
                    source=source_label,
                    target=target_label,
                    predicate=predicate,
                )
            return src_id, tgt_id
        except Exception as e:
            logger.error(
                f"链接记忆原子失败: {e}",
                source=source_label,
                target=target_label,
                predicate=predicate,
                exc_info=True,
            )
            raise

    # ------------------------------------------------------------------
    # 图遍历操作
    # ------------------------------------------------------------------

    def get_neighbors(self, node_id: str, depth: int = 1) -> list[dict]:
        """BFS 遍历获取邻居节点

        Args:
            node_id: 起始节点 ID（字符串形式，对应 GraphEdge 中存储的格式）
            depth: 遍历深度，1 表示只获取直接邻居，2 表示获取两度连接

        Returns:
            list[dict]: 邻居节点列表，每项包含：
                - node: 节点数据字典
                - edge_predicate: 到达该节点经过的边谓词
                - depth: 距起始节点的距离
        """
        try:
            visited: set[str] = {node_id}
            results: list[dict[str, Any]] = []
            queue: list[tuple[str, str | None, int]] = [(node_id, None, 0)]

            while queue:
                current_id, edge_predicate, current_depth = queue.pop(0)

                if current_depth > 0:
                    node_data = self.get_node(int(current_id))
                    if node_data:
                        results.append(
                            {
                                "node": node_data,
                                "edge_predicate": edge_predicate,
                                "depth": current_depth,
                            }
                        )

                if current_depth >= depth:
                    continue

                with self.db:
                    edges = GraphEdge.select().where(
                        (GraphEdge.source_node_id == current_id) | (GraphEdge.target_node_id == current_id)
                    )
                    for edge in edges:
                        neighbor_id = edge.target_node_id if edge.source_node_id == current_id else edge.source_node_id
                        if neighbor_id not in visited:
                            visited.add(neighbor_id)
                            queue.append((neighbor_id, edge.predicate, current_depth + 1))

            return results
        except Exception as e:
            logger.error(
                f"邻居遍历失败 (node_id={node_id}): {e}",
                exc_info=True,
            )
            return []

    def get_related_atoms(self, atom_id: str, max_depth: int = 2) -> list[str]:
        """通过图谱查找所有关联的记忆原子 ID

        BFS 遍历图结构，从包含 atom_id 的 GraphEntry 出发，
        沿实体节点边关系扩散，收集所有相连的 subject/object 值。

        Args:
            atom_id: 起始原子标识（匹配 GraphEntry.subject 或 .object）
            max_depth: 图遍历最大深度

        Returns:
            list[str]: 所有关联的原子 ID 列表（去重）
        """
        try:
            # Step 1: 从 GraphEntry 找到相关的实体标签
            with self.db:
                entries = GraphEntry.select().where((GraphEntry.subject == atom_id) | (GraphEntry.object == atom_id))
                if not entries:
                    return []

                labels: set[str] = set()
                for e in entries:
                    labels.add(e.subject)
                    labels.add(e.object)

            # Step 2: 通过 GraphNode BFS 遍历图
            with self.db:
                start_nodes = GraphNode.select().where(GraphNode.label.in_(list(labels)))
                start_ids: set[str] = {str(n.id) for n in start_nodes}

                if not start_ids:
                    return list(labels)

                visited: set[str] = set(start_ids)
                node_queue: list[tuple[str, int]] = [(sid, 0) for sid in start_ids]

                while node_queue:
                    current_id, d = node_queue.pop(0)
                    if d >= max_depth:
                        continue

                    edges = GraphEdge.select().where(
                        (GraphEdge.source_node_id == current_id) | (GraphEdge.target_node_id == current_id)
                    )
                    for edge in edges:
                        neighbor = edge.target_node_id if edge.source_node_id == current_id else edge.source_node_id
                        if neighbor not in visited:
                            visited.add(neighbor)
                            node_queue.append((neighbor, d + 1))

                # Step 3: 收集所有遍历到的节点标签
                all_node_ids = [int(nid) for nid in visited]
                nodes = GraphNode.select().where(GraphNode.id.in_(all_node_ids))
                for n in nodes:
                    labels.add(n.label)

                # Step 4: 收集关联的 GraphEntry subject/object
                result: set[str] = {atom_id}
                entry_list = GraphEntry.select().where(
                    (GraphEntry.subject.in_(list(labels))) | (GraphEntry.object.in_(list(labels)))
                )
                for e in entry_list:
                    result.add(e.subject)
                    result.add(e.object)

            return list(result)
        except Exception as e:
            logger.error(
                f"相关原子查询失败 (atom_id={atom_id}): {e}",
                exc_info=True,
            )
            return []

    def search_by_entity(self, entity_name: str, top_k: int = 10) -> list[dict]:
        """模糊搜索实体节点，返回节点及其关联的边和三元组

        Args:
            entity_name: 实体名称（LIKE 模糊匹配）
            top_k: 最大返回节点数

        Returns:
            list[dict]: 匹配结果列表，每项包含：
                - node: 节点字典
                - edges: 节点关联边列表
                - entries: 关联的三元组条目列表
        """
        try:
            with self.db:
                nodes = GraphNode.select().where(GraphNode.label ** f"%{entity_name}%").limit(top_k)

                results: list[dict[str, Any]] = []
                for node in nodes:
                    node_dict = self._node_to_dict(node)
                    sid = str(node.id)

                    connected_edges = GraphEdge.select().where(
                        (GraphEdge.source_node_id == sid) | (GraphEdge.target_node_id == sid)
                    )
                    related_entries = GraphEntry.select().where(
                        (GraphEntry.subject == node.label) | (GraphEntry.object == node.label)
                    )

                    results.append(
                        {
                            "node": node_dict,
                            "edges": [self._edge_to_dict(e) for e in connected_edges],
                            "entries": [self._entry_to_dict(e) for e in related_entries],
                        }
                    )

                return results
        except Exception as e:
            logger.error(
                f"实体搜索失败 (entity_name={entity_name}): {e}",
                exc_info=True,
            )
            return []

    # ------------------------------------------------------------------
    # Entry（三元组）操作
    # ------------------------------------------------------------------

    def add_entry(
        self,
        subject: str,
        predicate: str,
        obj: str,
        evidence: Optional[str] = None,
        confidence: float = 0.5,
    ) -> int:
        """创建 SPO 三元组条目

        Args:
            subject: 主语
            predicate: 谓词
            obj: 宾语
            evidence: 原文证据
            confidence: 置信度

        Returns:
            int: 条目 id
        """
        try:
            with self.db:
                entry = GraphEntry.create(
                    subject=subject,
                    predicate=predicate,
                    object=obj,
                    evidence=evidence,
                    confidence=confidence,
                )
            logger.debug(
                "图条目已创建",
                entry_id=entry.id,
                triple=f"({subject}, {predicate}, {obj})",
            )
            return entry.id
        except Exception as e:
            logger.error(
                f"创建图条目失败: {e}",
                subject=subject,
                predicate=predicate,
                obj=obj,
                exc_info=True,
            )
            raise

    def search_entries(
        self,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        obj: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """按 SPO 任意组合搜索三元组

        Args:
            subject: 主语（LIKE 匹配）
            predicate: 谓词（精确匹配）
            obj: 宾语（LIKE 匹配）

        Returns:
            list[dict]: 匹配的三元组字典列表
        """
        try:
            conditions = []
            if subject:
                conditions.append(GraphEntry.subject**subject)
            if predicate:
                conditions.append(GraphEntry.predicate == predicate)
            if obj:
                conditions.append(GraphEntry.object**obj)

            with self.db:
                if conditions:
                    query = GraphEntry.select().where(*conditions)
                else:
                    query = GraphEntry.select()
                return [self._entry_to_dict(e) for e in query]
        except Exception as e:
            logger.error(
                f"搜索图条目失败: {e}",
                subject=subject,
                predicate=predicate,
                obj=obj,
                exc_info=True,
            )
            return []

    def delete_entry(self, entry_id: int) -> bool:
        """删除指定三元组

        Args:
            entry_id: 条目 ID

        Returns:
            bool: 是否成功删除
        """
        try:
            with self.db:
                rows = GraphEntry.delete().where(GraphEntry.id == entry_id).execute()
            return rows > 0
        except Exception as e:
            logger.error(f"删除图条目失败 (entry_id={entry_id}): {e}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # 统计信息
    # ------------------------------------------------------------------

    def node_count(self) -> int:
        """返回图节点总数"""
        try:
            with self.db:
                return GraphNode.select().count()
        except Exception as e:
            logger.error(f"统计图节点数失败: {e}", exc_info=True)
            return 0

    def edge_count(self) -> int:
        """返回图边总数"""
        try:
            with self.db:
                return GraphEdge.select().count()
        except Exception as e:
            logger.error(f"统计图边数失败: {e}", exc_info=True)
            return 0

    def entry_count(self) -> int:
        """返回三元组条目总数"""
        try:
            with self.db:
                return GraphEntry.select().count()
        except Exception as e:
            logger.error(f"统计图条目数失败: {e}", exc_info=True)
            return 0

    def get_stats(self) -> dict[str, int]:
        """返回完整图统计信息

        Returns:
            dict: 包含 node_count / edge_count / entry_count
        """
        return {
            "node_count": self.node_count(),
            "edge_count": self.edge_count(),
            "entry_count": self.entry_count(),
        }

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    @staticmethod
    def _node_to_dict(node: GraphNode) -> dict[str, Any]:
        """将 GraphNode Peewee 实例转为字典"""
        data: dict[str, Any] = {
            "id": node.id,
            "node_type": node.node_type,
            "label": node.label,
        }
        if node.properties:
            try:
                data["properties"] = json.loads(node.properties)
            except (json.JSONDecodeError, TypeError):
                data["properties"] = node.properties
        return data

    @staticmethod
    def _edge_to_dict(edge: GraphEdge) -> dict[str, Any]:
        """将 GraphEdge Peewee 实例转为字典"""
        return {
            "id": edge.id,
            "source_node_id": int(edge.source_node_id),
            "target_node_id": int(edge.target_node_id),
            "predicate": edge.predicate,
            "confidence": edge.confidence,
        }

    @staticmethod
    def _entry_to_dict(entry: GraphEntry) -> dict[str, Any]:
        """将 GraphEntry Peewee 实例转为字典"""
        return {
            "id": entry.id,
            "subject": entry.subject,
            "predicate": entry.predicate,
            "object": entry.object,
            "evidence": entry.evidence,
            "confidence": entry.confidence,
        }
