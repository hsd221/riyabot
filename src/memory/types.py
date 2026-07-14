"""TypedDict 类型定义 — 记忆系统的字典形状类型标注

为 src/memory/ 中各模块使用的字典形状提供精确类型定义，
使基于类型检查器（basedpyright）能验证字典键的访问合法性。
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class AtomDict(TypedDict):
    """记忆原子字典 — 对应 _model_to_result / _atom_to_dict 的输出

    Attributes:
        atom_id: 原子唯一 ID
        atom_type: 原子类型（episodic / factual / relational 等）
        content: 原子文本内容
        importance: 重要性评分
        confidence: 置信度
        weight: 综合权重
        ttl_days: 存活天数
        decay_type: 衰减类型
        reinforcement_count: 强化次数
        source_scene: 来源场景
        source_id: 来源聊天流 ID
        privacy_level: 隐私级别
        status: 原子状态
        fade_level: 褪色等级（仅检索结果）
        created_at: 创建时间（ISO 格式）
        last_accessed_at: 最后访问时间
        last_reinforced_at: 最后强化时间
        entities: 关联实体列表
        trace_chain_id: 追踪链 ID
        embedding_id: 向量 ID
        final_score: 综合排序得分（仅 rank_atoms 输出）
        similarity_score: 向量相似度得分（检索阶段输出）
        relevance_score: 与当前查询的相关度得分（检索阶段输出）
    """

    atom_id: str
    atom_type: str
    content: str
    importance: float
    confidence: float
    weight: float
    ttl_days: int
    decay_type: str
    reinforcement_count: int
    source_scene: str
    source_id: NotRequired[str | None]
    privacy_level: str
    status: str
    fade_level: str
    created_at: NotRequired[str | None]
    last_accessed_at: NotRequired[str | None]
    last_reinforced_at: NotRequired[str | None]
    entities: NotRequired[list[str] | str]
    trace_chain_id: NotRequired[str | None]
    embedding_id: NotRequired[str]
    final_score: NotRequired[float]
    similarity_score: NotRequired[float]
    relevance_score: NotRequired[float]


class InsightItem(TypedDict):
    """洞察条目 — 对应 InsightEngine 各扫描方法的输出

    Attributes:
        content: 洞察文本内容
        source_atoms: 关联原子 ID 的 JSON 字符串，无可为 None
        confidence: 置信度
        insight_type: 洞察类型（可选）
        generated_at: 生成时间（可选）
        related_entities: 关联实体列表（可选）
    """

    content: str
    source_atoms: str | None
    confidence: float
    insight_type: NotRequired[str]
    generated_at: NotRequired[str]
    related_entities: NotRequired[list[str]]


class TopicSummary(TypedDict):
    """话题摘要 — 对应 TopicState.to_summary_dict() 的输出

    Attributes:
        topic_id: 话题 ID
        keywords: 关键词列表
        key_points: 关键点列表
        participant_count: 参与人数
        message_count: 消息总数
        first_seen: 首次出现时间戳
        last_updated: 最后更新时间戳
        is_closed: 是否关闭
        topic_title: 话题标题（LLM 分段判断时生成）
        start_message_id: 话题起始消息 ID
        end_message_id: 话题结束消息 ID
        messages: 话题包含的消息快照，用于未闭合尾段续传
    """

    topic_id: str
    keywords: list[str]
    key_points: list[str]
    participant_count: int
    message_count: int
    first_seen: float
    last_updated: float
    is_closed: bool
    topic_title: NotRequired[str]
    start_message_id: NotRequired[str]
    end_message_id: NotRequired[str]
    messages: NotRequired[list[dict[str, Any]]]


class PayloadSchemaField(TypedDict):
    """Qdrant payload schema 字段定义

    Attributes:
        name: 字段名
        type: 字段类型（keyword / float 等）
        index: 是否创建索引（可选）
    """

    name: str
    type: str
    index: NotRequired[bool]


class BufferMessage(TypedDict):
    """编码缓冲区消息 — 对应 EncodingBuffer.messages 的元素

    Attributes:
        user_id: 用户 ID
        message_id: 原始消息 ID（可选，用于去重）
        speaker: 发言人名称
        content: 消息内容
        timestamp: 时间戳
        is_self: 是否机器人自身消息（可选）
        platform: 消息发送者所属平台（可选）
        nickname: 平台昵称（可选）
        cardname: 群名片（可选）
        group_id: 群 ID（可选）
        group_name: 群名称（可选）
    """

    user_id: str
    message_id: NotRequired[str]
    speaker: str
    content: str
    timestamp: float
    is_self: NotRequired[bool]
    platform: NotRequired[str]
    nickname: NotRequired[str]
    cardname: NotRequired[str]
    group_id: NotRequired[str]
    group_name: NotRequired[str]


class RollbackAction(TypedDict):
    """WriteOp 回滚步骤

    Attributes:
        action: 回滚操作类型
        atom_id: 关联原子 ID
        original_data: 原始数据备份
    """

    action: str
    atom_id: str
    original_data: dict[str, Any]


class NeighborResult(TypedDict):
    """图邻居节点 — GraphStore.get_neighbors() 的返回元素

    Attributes:
        node: 节点数据字典
        edge_predicate: 到达该节点经过的边谓词
        depth: 距离起始节点的 BFS 深度
        path: 路径节点 ID 列表（可选）
    """

    node: dict[str, Any]
    edge_predicate: str
    depth: int
    path: NotRequired[list[str]]


class EntitySearchResult(TypedDict):
    """实体搜索结果 — GraphStore.search_by_entity() 的返回元素

    Attributes:
        node: 匹配节点字典
        edges: 节点关联边列表
        entries: 关联的三元组条目列表
    """

    node: dict[str, Any]
    edges: list[dict[str, Any]]
    entries: list[dict[str, Any]]


class MoodEntry(TypedDict):
    """情绪历史条目 — UserProfile.mood_history 的元素

    Attributes:
        timestamp: 时间戳（ISO 格式）
        sensory_tags: 感官标签列表
        emotion_tags: 情绪标签列表
        temporal_context: 时间上下文（可选）
        content: 关联内容摘要
    """

    timestamp: str
    sensory_tags: list[str]
    emotion_tags: list[str]
    temporal_context: NotRequired[str | None]
    content: str
