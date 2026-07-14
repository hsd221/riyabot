"""MaiBot 记忆系统 — 存储层

提供统一的记忆存储入口：MemoryStore 单例封装 SQLite + Qdrant 双层存储。

使用方式:
    from src.memory import MemoryStore, get_memory_store

    # 初始化（启动时）
    store = MemoryStore(MemoryStoreConfig())
    await store.initialize()

    # 获取实例（运行时）
    store = get_memory_store()
"""

from src.memory.atom import MemoryAtom, AtomType, DecayType, EpisodicDetail, SemanticDetail
from src.memory.atom_association import AtomAssociation, AtomAssociationStore, AssociationType
from src.memory.bm25_retrieval import BM25Retriever, reciprocal_rank_fusion
from src.memory.schema import AtomAssociationModel
from src.memory.conflict_arbitration import ConflictArbiter, ConflictDecision, Resolution
from src.memory.dream_agent import DreamTask
from src.memory.dream_weaver import DreamWeaver
from src.memory.encoding_pipeline import EncodingPipeline, EncodingTask, get_encoding_pipeline
from src.memory.expression_bridge import ExpressionBridge, ExpressionProfile
from src.memory.inspiration_engine import InspirationEngine
from src.memory.feedback import ReinforcementTracker
from src.memory.forgetting import ForgettingManager, ForgettingSweepTask
from src.memory.graph_store import GraphStore
from src.memory.insight_engine import InsightEngine
from src.memory.layer0_archive import MessageArchiver
from src.memory.layer1_summarizer import SavedTopic, UnclosedTopicBridge
from src.memory.layer2_encoder import BatchEncoder, EncodingBuffer
from src.memory.layer3_retrieval import PrivacyFilter
from src.memory.objectivity_check import (
    CheckResult,
    ConflictInfo,
    ObjectivityChecker,
    check_contradiction,
    compute_content_similarity,
)
from src.memory.prompt_integration import build_memory_retrieval_prompt
from src.memory.store import MemoryStore, MemoryStoreConfig, QdrantManager, QDRANT_AVAILABLE
from src.memory.trace_chain import TraceChainRecorder, TraceStep
from src.memory.user_profile import (
    PersonIdentity,
    ProfileBuilder,
    ProfileRetriever,
    ProfileStore,
    UserProfile,
    UserProfileModel,
)

__all__ = [
    "AtomAssociation",
    "AtomAssociationModel",
    "AtomAssociationStore",
    "AssociationType",
    "AtomType",
    "BatchEncoder",
    "BM25Retriever",
    "build_memory_retrieval_prompt",
    "CheckResult",
    "ConflictArbiter",
    "ConflictDecision",
    "ConflictInfo",
    "DecayType",
    "DreamTask",
    "DreamWeaver",
    "EncodingBuffer",
    "ExpressionBridge",
    "ExpressionProfile",
    "EncodingPipeline",
    "EncodingTask",
    "EpisodicDetail",
    "ForgettingManager",
    "ForgettingSweepTask",
    "GraphStore",
    "InspirationEngine",
    "InsightEngine",
    "MemoryAtom",
    "MemoryStore",
    "MemoryStoreConfig",
    "MessageArchiver",
    "ObjectivityChecker",
    "ProfileBuilder",
    "PersonIdentity",
    "ProfileRetriever",
    "ProfileStore",
    "Resolution",
    "QdrantManager",
    "QDRANT_AVAILABLE",
    "SavedTopic",
    "SemanticDetail",
    "UnclosedTopicBridge",
    "UserProfile",
    "UserProfileModel",
    "check_contradiction",
    "compute_content_similarity",
    "get_encoding_pipeline",
    "get_memory_store",
    "PrivacyFilter",
    "reciprocal_rank_fusion",
    "ReinforcementTracker",
    "TraceChainRecorder",
    "TraceStep",
]


def get_memory_store() -> MemoryStore:
    """获取 MemoryStore 单例实例"""
    return MemoryStore.get_instance()
